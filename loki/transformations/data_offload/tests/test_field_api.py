# (C) Copyright 2018- ECMWF.
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.

import pytest

from loki import Sourcefile
from loki.frontend import available_frontends
from loki.logging import log_levels
from loki.ir import FindNodes, Pragma, CallStatement
import loki.expression.symbols as sym
from loki.module import Module
from loki.transformations import FieldOffloadTransformation


@pytest.fixture(name="parkind_mod")
def fixture_parkind_mod(tmp_path, frontend):
    fcode = """
    module parkind1
      integer, parameter :: jprb=4
    end module
    """
    return Module.from_source(fcode, frontend=frontend, xmods=[tmp_path])

@pytest.fixture(name="field_module")
def fixture_field_module(tmp_path, frontend):
    fcode = """
    module field_module
      implicit none

      type field_2rb
        real, pointer :: f_ptr(:,:,:)
      end type field_2rb

      type field_3rb
        real, pointer :: f_ptr(:,:,:)
     contains
        procedure :: update_view
      end type field_3rb
      
      type field_4rb
        real, pointer :: f_ptr(:,:,:)
     contains
        procedure :: update_view
      end type field_4rb

    contains
    subroutine update_view(self, idx)
      class(field_3rb), intent(in)  :: self
      integer, intent(in)           :: idx
    end subroutine
    end module
    """
    return Module.from_source(fcode,  frontend=frontend, xmods=[tmp_path])


@pytest.mark.parametrize('frontend', available_frontends())
def test_field_offload(frontend, parkind_mod, field_module, tmp_path):  # pylint: disable=unused-argument
    fcode = """
    module driver_mod
      use parkind1, only: jprb
      use field_module, only: field_2rb, field_3rb
      implicit none

      type state_type
        real(kind=jprb), dimension(10,10), pointer :: a, b, c
        class(field_3rb), pointer :: f_a, f_b, f_c
        contains
        procedure :: update_view => state_update_view
      end type state_type

    contains

      subroutine state_update_view(self, idx)
        class(state_type), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine

      subroutine kernel_routine(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real(kind=jprb), intent(in)     :: a(nlon,nlev)
        real(kind=jprb), intent(inout)  :: b(nlon,nlev)
        real(kind=jprb), intent(out)    :: c(nlon,nlev)
        integer :: i, j

        do j=1, nlon
          do i=1, nlev
            b(i,j) = a(i,j) + 0.1
            c(i,j) = 0.1
          end do
        end do
      end subroutine kernel_routine

      subroutine driver_routine(nlon, nlev, state)
        integer, intent(in)             :: nlon, nlev
        type(state_type), intent(inout) :: state
        integer                         :: i

        !$loki data
        do i=1,nlev
            call state%update_view(i)
            call kernel_routine(nlon, nlev, state%a, state%b, state%c)
        end do
        !$loki end data

      end subroutine driver_routine
    end module driver_mod
    """
    driver_mod = Sourcefile.from_source(fcode, frontend=frontend, xmods=[tmp_path])['driver_mod']
    driver = driver_mod['driver_routine']
    deviceptr_prefix = 'loki_devptr_prefix_'
    driver.apply(FieldOffloadTransformation(devptr_prefix=deviceptr_prefix,
                                            offload_index='i',
                                            field_group_types=['state_type']),
                 role='driver',
                 targets=['kernel_routine'])

    calls = FindNodes(CallStatement).visit(driver.body)
    kernel_call = next(c for c in calls if c.name=='kernel_routine')

    # verify that field offloads are generated properly
    in_calls = [c for c in calls if 'get_device_data_rdonly' in c.name.name.lower()]
    assert len(in_calls) == 1
    inout_calls = [c for c in calls if 'get_device_data_rdwr' in c.name.name.lower()]
    assert len(inout_calls) == 2
    # verify that field sync host calls are generated properly
    sync_calls = [c for c in calls if 'sync_host_rdwr' in c.name.name.lower()]
    assert len(sync_calls) == 2

    # verify that data offload pragmas remain
    pragmas = FindNodes(Pragma).visit(driver.body)
    assert len(pragmas) == 2
    assert all(p.keyword=='loki' and p.content==c for p, c in zip(pragmas, ['data', 'end data']))

    # verify that new pointer variables are created and used in driver calls
    for var in ['state_a', 'state_b', 'state_c']:
        name = deviceptr_prefix + var
        assert name in driver.variable_map
        devptr = driver.variable_map[name]
        assert isinstance(devptr, sym.Array)
        assert len(devptr.shape) == 3
        assert devptr.name in (arg.name for arg in kernel_call.arguments)


@pytest.mark.parametrize('frontend', available_frontends())
def test_field_offload_slices(frontend, parkind_mod, field_module, tmp_path):  # pylint: disable=unused-argument
    fcode = """
    module driver_mod
      use parkind1, only: jprb
      use field_module, only: field_4rb
      implicit none

      type state_type
        real(kind=jprb), dimension(10,10,10), pointer :: a, b, c, d
        class(field_4rb), pointer :: f_a, f_b, f_c, f_d
        contains
        procedure :: update_view => state_update_view
      end type state_type

    contains

      subroutine state_update_view(self, idx)
        class(state_type), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine

      subroutine kernel_routine(nlon, nlev, a, b, c, d)
        integer, intent(in)             :: nlon, nlev
        real(kind=jprb), intent(in)     :: a(nlon,nlev,nlon)
        real(kind=jprb), intent(inout)  :: b(nlon,nlev)
        real(kind=jprb), intent(out)    :: c(nlon)
        real(kind=jprb), intent(in)     :: d(nlon,nlev,nlon)
        integer :: i, j
      end subroutine kernel_routine

      subroutine driver_routine(nlon, nlev, state)
        integer, intent(in)             :: nlon, nlev
        type(state_type), intent(inout) :: state
        integer                         :: i
        !$loki data
        do i=1,nlev
            call kernel_routine(nlon, nlev, state%a(:,:,1), state%b(:,1,1), state%c(1,1,1), state%d)
        end do
        !$loki end data

      end subroutine driver_routine
    end module driver_mod
    """
    driver_mod = Sourcefile.from_source(fcode, frontend=frontend, xmods=[tmp_path])['driver_mod']
    driver = driver_mod['driver_routine']
    deviceptr_prefix = 'loki_devptr_prefix_'
    driver.apply(FieldOffloadTransformation(devptr_prefix=deviceptr_prefix,
                                            offload_index='i',
                                            field_group_types=['state_type']),
                 role='driver',
                 targets=['kernel_routine'])

    calls = FindNodes(CallStatement).visit(driver.body)
    kernel_call = next(c for c in calls if c.name=='kernel_routine')
    # verify that new pointer variables are created and used in driver calls
    for var, rank in zip(['state_d', 'state_a', 'state_b', 'state_c',], [4, 3, 2, 1]):
        name = deviceptr_prefix + var
        assert name in driver.variable_map
        devptr = driver.variable_map[name]
        assert isinstance(devptr, sym.Array)
        assert len(devptr.shape) == 4
        assert devptr.name in (arg.name for arg in kernel_call.arguments)
        arg = next(arg for arg in kernel_call.arguments if devptr.name in arg.name)
        assert arg.dimensions == ((sym.RangeIndex((None,None)),)*(rank-1) +
                                 (sym.IntLiteral(1),)*(4-rank) +
                                 (sym.Scalar(name='i'),))


@pytest.mark.parametrize('frontend', available_frontends())
def test_field_offload_multiple_calls(frontend, parkind_mod, field_module, tmp_path):  # pylint: disable=unused-argument
    fcode = """
    module driver_mod
      use parkind1, only: jprb
      use field_module, only: field_2rb, field_3rb
      implicit none

      type state_type
        real(kind=jprb), dimension(10,10), pointer :: a, b, c
        class(field_3rb), pointer :: f_a, f_b, f_c
        contains
        procedure :: update_view => state_update_view
      end type state_type

    contains

      subroutine state_update_view(self, idx)
        class(state_type), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine

      subroutine kernel_routine(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real(kind=jprb), intent(in)     :: a(nlon,nlev)
        real(kind=jprb), intent(inout)  :: b(nlon,nlev)
        real(kind=jprb), intent(out)    :: c(nlon,nlev)
        integer :: i, j

        do j=1, nlon
          do i=1, nlev
            b(i,j) = a(i,j) + 0.1
            c(i,j) = 0.1
          end do
        end do
      end subroutine kernel_routine

      subroutine driver_routine(nlon, nlev, state)
        integer, intent(in)             :: nlon, nlev
        type(state_type), intent(inout) :: state
        integer                         :: i

        !$loki data
        do i=1,nlev
            call state%update_view(i)

            call kernel_routine(nlon, nlev, state%a, state%b, state%c)

            call kernel_routine(nlon, nlev, state%a, state%b, state%c)
        end do
        !$loki end data

      end subroutine driver_routine
    end module driver_mod
    """

    driver_mod = Sourcefile.from_source(fcode, frontend=frontend, xmods=[tmp_path])['driver_mod']
    driver = driver_mod['driver_routine']
    deviceptr_prefix = 'loki_devptr_prefix_'
    driver.apply(FieldOffloadTransformation(devptr_prefix=deviceptr_prefix,
                                            offload_index='i',
                                            field_group_types=['state_type']),
                 role='driver',
                 targets=['kernel_routine'])
    calls = FindNodes(CallStatement).visit(driver.body)
    kernel_calls = [c for c in calls if c.name=='kernel_routine']

    # verify that field offloads are generated properly
    in_calls = [c for c in calls if 'get_device_data_rdonly' in c.name.name.lower()]
    assert len(in_calls) == 1
    inout_calls = [c for c in calls if 'get_device_data_rdwr' in c.name.name.lower()]
    assert len(inout_calls) == 2
    # verify that field sync host calls are generated properly
    sync_calls = [c for c in calls if 'sync_host_rdwr' in c.name.name.lower()]
    assert len(sync_calls) == 2

    # verify that data offload pragmas remain
    pragmas = FindNodes(Pragma).visit(driver.body)
    assert len(pragmas) == 2
    assert all(p.keyword=='loki' and p.content==c for p, c in zip(pragmas, ['data', 'end data']))

    # verify that new pointer variables are created and used in driver calls
    for var in ['state_a', 'state_b', 'state_c']:
        name = deviceptr_prefix + var
        assert name in driver.variable_map
        devptr = driver.variable_map[name]
        assert isinstance(devptr, sym.Array)
        assert len(devptr.shape) == 3
        assert devptr.name in (arg.name for kernel_call in kernel_calls for arg in kernel_call.arguments)


@pytest.mark.parametrize('frontend', available_frontends())
def test_field_offload_no_targets(frontend, parkind_mod, field_module, tmp_path):  # pylint: disable=unused-argument
    fother = """
    module another_module
      implicit none
    contains
      subroutine another_kernel(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real, intent(in)     :: a(nlon,nlev)
        real, intent(inout)  :: b(nlon,nlev)
        real, intent(out)    :: c(nlon,nlev)
        integer :: i, j
      end subroutine
    end module
    """
    fcode = """
    module driver_mod
      use parkind1, only: jprb
      use field_module, only: field_2rb, field_3rb
      use another_module, only: another_kernel

      implicit none

      type state_type
        real(kind=jprb), dimension(10,10), pointer :: a, b, c
        class(field_3rb), pointer :: f_a, f_b, f_c
        contains
        procedure :: update_view => state_update_view
      end type state_type

    contains

      subroutine state_update_view(self, idx)
        class(state_type), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine

      subroutine kernel_routine(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real(kind=jprb), intent(in)     :: a(nlon,nlev)
        real(kind=jprb), intent(inout)  :: b(nlon,nlev)
        real(kind=jprb), intent(out)    :: c(nlon,nlev)
        integer :: i, j

        do j=1, nlon
          do i=1, nlev
            b(i,j) = a(i,j) + 0.1
            c(i,j) = 0.1
          end do
        end do
      end subroutine kernel_routine

      subroutine driver_routine(nlon, nlev, state)
        integer, intent(in)             :: nlon, nlev
        type(state_type), intent(inout) :: state
        integer                         :: i

        !$loki data
        do i=1,nlev
            call state%update_view(i)
            call another_kernel(nlon, state%a, state%b, state%c)
        end do
        !$loki end data

      end subroutine driver_routine
    end module driver_mod
    """

    Sourcefile.from_source(fother, frontend=frontend, xmods=[tmp_path])
    driver_mod = Sourcefile.from_source(fcode, frontend=frontend, xmods=[tmp_path])['driver_mod']
    driver = driver_mod['driver_routine']
    deviceptr_prefix = 'loki_devptr_prefix_'
    driver.apply(FieldOffloadTransformation(devptr_prefix=deviceptr_prefix,
                                            offload_index='i',
                                            field_group_types=['state_type']),
                 role='driver',
                 targets=['kernel_routine'])

    calls = FindNodes(CallStatement).visit(driver.body)
    assert not any(c for c in calls if c.name=='kernel_routine')

    # verify that no field offloads are generated
    in_calls = [c for c in calls if 'get_device_data_rdonly' in c.name.name.lower()]
    assert len(in_calls) == 0
    inout_calls = [c for c in calls if 'get_device_data_rdwr' in c.name.name.lower()]
    assert len(inout_calls) == 0
    # verify that no field sync host calls are generated
    sync_calls = [c for c in calls if 'sync_host_rdwr' in c.name.name.lower()]
    assert len(sync_calls) == 0

    # verify that data offload pragmas remain
    pragmas = FindNodes(Pragma).visit(driver.body)
    assert len(pragmas) == 2
    assert all(p.keyword=='loki' and p.content==c for p, c in zip(pragmas, ['data', 'end data']))


@pytest.mark.parametrize('frontend', available_frontends())
def test_field_offload_unknown_kernel(caplog, frontend, parkind_mod, field_module, tmp_path):  # pylint: disable=unused-argument
    fother = """
    module another_module
      implicit none
    contains
      subroutine another_kernel(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real, intent(in)     :: a(nlon,nlev)
        real, intent(inout)  :: b(nlon,nlev)
        real, intent(out)    :: c(nlon,nlev)
        integer :: i, j
      end subroutine
    end module
    """
    fcode = """
    module driver_mod
      use parkind1, only: jprb
      use another_module, only: another_kernel
      implicit none

      type state_type
        real(kind=jprb), dimension(10,10), pointer :: a, b, c
        class(field_3rb), pointer :: f_a, f_b, f_c
        contains
        procedure :: update_view => state_update_view
      end type state_type

    contains

     subroutine state_update_view(self, idx)
        class(state_type), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine

      subroutine driver_routine(nlon, nlev, state)
        integer, intent(in)             :: nlon, nlev
        type(state_type), intent(inout) :: state
        integer                         :: i

        !$loki data
        do i=1,nlev
            call state%update_view(i)
            call another_kernel(nlon, nlev, state%a, state%b, state%c)
        end do
        !$loki end data

      end subroutine driver_routine
    end module driver_mod
    """

    Sourcefile.from_source(fother, frontend=frontend, xmods=[tmp_path])
    driver_mod = Sourcefile.from_source(fcode, frontend=frontend, xmods=[tmp_path])['driver_mod']
    driver = driver_mod['driver_routine']
    deviceptr_prefix = 'loki_devptr_prefix_'

    field_offload_trafo = FieldOffloadTransformation(devptr_prefix=deviceptr_prefix,
                                                         offload_index='i',
                                                         field_group_types=['state_type'])
    caplog.clear()
    with caplog.at_level(log_levels['ERROR']):
        with pytest.raises(RuntimeError):
            driver.apply(field_offload_trafo, role='driver', targets=['another_kernel'])
        assert len(caplog.records) == 1
        assert ('[Loki] Data offload: Routine driver_routine has not been enriched '+
                'in another_kernel') in caplog.records[0].message


@pytest.mark.parametrize('frontend', available_frontends())
def test_field_offload_warnings(caplog, frontend, parkind_mod, field_module, tmp_path):  # pylint: disable=unused-argument
    fother_state = """
    module state_type_mod
      implicit none
      type state_type2
        real, dimension(10,10), pointer :: a, b, c
      contains
        procedure :: update_view => state_update_view
      end type state_type2

    contains

      subroutine state_update_view(self, idx)
        class(state_type2), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine
    end module
    """
    fother_mod= """
    module another_module
      implicit none
    contains
      subroutine another_kernel(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real, intent(in)     :: a(nlon,nlev)
        real, intent(inout)  :: b(nlon,nlev)
        real, intent(out)    :: c(nlon,nlev)
        integer :: i, j
      end subroutine
    end module
    """
    fcode = """
    module driver_mod
      use state_type_mod, only: state_type2
      use parkind1, only: jprb
      use field_module, only: field_2rb, field_3rb
      use another_module, only: another_kernel

      implicit none

      type state_type
        real(kind=jprb), dimension(10,10), pointer :: a, b, c
        class(field_3rb), pointer :: f_a, f_b, f_c
        contains
        procedure :: update_view => state_update_view
      end type state_type

    contains

      subroutine state_update_view(self, idx)
        class(state_type), intent(in) :: self
        integer, intent(in)           :: idx
      end subroutine

      subroutine kernel_routine(nlon, nlev, a, b, c)
        integer, intent(in)             :: nlon, nlev
        real(kind=jprb), intent(in)     :: a(nlon,nlev)
        real(kind=jprb), intent(inout)  :: b(nlon,nlev)
        real(kind=jprb), intent(out)    :: c(nlon,nlev)
        integer :: i, j

        do j=1, nlon
          do i=1, nlev
            b(i,j) = a(i,j) + 0.1
            c(i,j) = 0.1
          end do
        end do
      end subroutine kernel_routine

      subroutine driver_routine(nlon, nlev, state, state2)
        integer, intent(in)             :: nlon, nlev
        type(state_type), intent(inout) :: state
        type(state_type2), intent(inout) :: state2

        integer                         :: i
        real(kind=jprb)                 :: a(nlon,nlev)
        real, pointer                   :: loki_devptr_prefix_state_b

        !$loki data
        do i=1,nlev
            call state%update_view(i)
            call kernel_routine(nlon, nlev, a, state%b, state2%c)
        end do
        !$loki end data

      end subroutine driver_routine
    end module driver_mod
    """
    Sourcefile.from_source(fother_state, frontend=frontend, xmods=[tmp_path])
    Sourcefile.from_source(fother_mod, frontend=frontend, xmods=[tmp_path])
    driver_mod = Sourcefile.from_source(fcode, frontend=frontend, xmods=[tmp_path])['driver_mod']
    driver = driver_mod['driver_routine']
    deviceptr_prefix = 'loki_devptr_prefix_'

    field_offload_trafo = FieldOffloadTransformation(devptr_prefix=deviceptr_prefix,
                                                         offload_index='i',
                                                         field_group_types=['state_type'])
    caplog.clear()
    with caplog.at_level(log_levels['WARNING']):
        driver.apply(field_offload_trafo, role='driver', targets=['kernel_routine'])
        assert len(caplog.records) == 3
        assert (('[Loki] Data offload: Raw array object a encountered in'
                 +' driver_routine that is not wrapped by a Field API object')
                in caplog.records[0].message)
        assert ('[Loki] Data offload: The parent object state2 of type state_type2 is not in the' +
                ' list of field wrapper types') in caplog.records[1].message
        assert ('[Loki] Data offload: The routine driver_routine already has a' +
                ' variable named loki_devptr_prefix_state_b') in caplog.records[2].message
