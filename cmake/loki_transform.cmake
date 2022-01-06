macro( _loki_transform_parse_args _func_name )

    if( _PAR_UNPARSED_ARGUMENTS )
        ecbuild_critical( "Unknown keywords given to ${_func_name}(): \"${_PAR_UNPARSED_ARGUMENTS}\"" )
    endif()

    if( NOT _PAR_OUTPUT )
        ecbuild_critical( "No OUTPUT specified for ${_func_name}()" )
    endif()

    if( NOT _PAR_DEPENDS )
        ecbuild_critical( "No DEPENDS specified for ${_func_name}()" )
    endif()

    if( NOT _PAR_FRONTEND )
        ecbuild_critical( "No FRONTEND specified for ${_func_name}()" )
    endif()
    list( APPEND _ARGS --frontend ${_PAR_FRONTEND} )

    if( ${_PAR_CPP} )
        list( APPEND _ARGS --cpp )
    endif()

    if( _PAR_OUTPATH )
        file( MAKE_DIRECTORY ${_PAR_OUTPATH} )
        list( APPEND _ARGS --out-path ${_PAR_OUTPATH} )
    endif()

    if( _PAR_HEADER )
        foreach( _HEADER ${_PAR_HEADER} )
            list( APPEND _ARGS --header ${_HEADER} )
        endforeach()
    endif()

    if( _PAR_INCLUDE )
        foreach( _INCLUDE ${_PAR_INCLUDE} )
            list( APPEND _ARGS --include ${_INCLUDE} )
        endforeach()
    endif()

    if( _PAR_DEFINE )
        foreach( _DEFINE ${_PAR_DEFINE} )
            list( APPEND _ARGS --define ${_DEFINE} )
        endforeach()
    endif()

    if( _PAR_XMOD )
        foreach( _XMOD ${_PAR_XMOD} )
            file( MAKE_DIRECTORY ${XMOD_DIR} )
            list( APPEND _ARGS --xmod ${_XMOD} )
        endforeach()
    endif()

    set( _LOKI_TRANSFORM_ENV )
    set( _LOKI_TRANSFORM_PATH )

    if( TARGET clawfc AND ${_PAR_FRONTEND} STREQUAL "omni" )
        # Ugly hack but I don't have a better solution: We need to add F_FRONT
        # (which is installed in the same directory as clawfc) to the PATH, if
        # OMNI is used as a frontend. Hence we have to update the environment in the below
        # add_custom_command calls to loki-transform.py.
        get_target_property( _CLAWFC_EXECUTABLE clawfc IMPORTED_LOCATION )
        get_filename_component( _CLAWFC_LOCATION ${_CLAWFC_EXECUTABLE} DIRECTORY )
        list( APPEND _LOKI_TRANSFORM_PATH ${_CLAWFC_LOCATION} )
    endif()

    if( _PAR_OUTPATH AND (${_PAR_FRONTEND} STREQUAL "omni" OR ${_PAR_FRONTEND} STREQUAL "ofp") )
        # With pre-processing, we may end up having a race condition on the preprocessed
        # source files in parallel builds. Ensuring we use the outpath of the call to Loki
        # should ensure in most cases that parallel builds write to different directories
        # Note: this does not affect Fparser as we don't have to write preprocessed files
        # to disk there
        list( APPEND _LOKI_TRANSFORM_ENV LOKI_TMP_DIR=${_PAR_OUTPATH} )
    endif()

    if( _LOKI_TRANSFORM_ENV OR _LOKI_TRANSFORM_PATH )
        if( TARGET loki-transform.py )
            # Unfortunately, an environment update breaks the CMake feature of recognizing
            # the executable in add_custom_command as a previously declared target, which would
            # enable choosing the correct path automatically. Therefore, we have to insert also
            # loki-transform.py into the PATH variable.
            get_target_property( _LOKI_TRANSFORM_EXECUTABLE loki-transform.py IMPORTED_LOCATION )
            get_filename_component( _LOKI_TRANSFORM_LOCATION ${_LOKI_TRANSFORM_EXECUTABLE} DIRECTORY )
            list( APPEND _LOKI_TRANSFORM_PATH ${_LOKI_TRANSFORM_LOCATION} )
        endif()

        # Join all declared paths
        string( REPLACE ";" ":" _LOKI_TRANSFORM_PATH "${_LOKI_TRANSFORM_PATH}" )
        list( APPEND _LOKI_TRANSFORM_ENV PATH=${_LOKI_TRANSFORM_PATH}:$ENV{PATH} )

        # Run loki-transform.py via the CMake ENV wrapper
        set( _LOKI_TRANSFORM ${CMAKE_COMMAND} -E env ${_LOKI_TRANSFORM_ENV} loki-transform.py )

        # Also, now it breaks the dependency chain and we have to declare manual dependencies on
        # loki-transform.py...
        set( _LOKI_TRANSFORM_DEPENDENCY loki-transform.py )
    else()
        # This is how it is meant to be: We can rely on CMake's ability to set the correct
        # path of loki-transform.py if it was declared as an executable before (otherwise it
        # will assume it has been already on the path when CMake was called
        set( _LOKI_TRANSFORM loki-transform.py )
        set( _LOKI_TRANSFORM_DEPENDENCY "" )
    endif()

endmacro()

##############################################################################
# .rst:
#
# loki_transform_convert
# ======================
#
# Apply Loki transformation in convert mode.::
#
#   loki_transform_convert(
#       OUTPUT <outfile1> [<outfile2> ...]
#       DEPENDS <dependency1> [<dependency2> ...]
#       MODE <mode>
#       FRONTEND <frontend>
#       [CPP]
#       [CONFIG <config-file>]
#       [PATH <path>]
#       [OUTPATH <outpath>]
#       [INCLUDE <include1> [<include2> ...]]
#       [HEADER <header1> [<header2> ...]]
#       [DEFINE <define1> [<define2> ...]]
#       [OMNI_INCLUDE <omni-inc1> [<omni-inc2> ...]]
#       [XMOD <xmod-dir1> [<xmod-dir2> ...]]
#       [REMOVE_OPENMP] [DATA_OFFLOAD]
#   )
#
# Call ``loki-transform.py convert ...`` with the provided arguments.
# See ``loki-transform.py`` for a description of all options.
#
# Options
# -------
#
# :OUTPUT:     The output files generated by Loki. Providing them here allows
#              to declare dependencies on this command later.
# :DEPENDS:    The input files or targets this call depends on.
#
##############################################################################

function( loki_transform_convert )

    set( options CPP DATA_OFFLOAD REMOVE_OPENMP )
    set( oneValueArgs MODE FRONTEND CONFIG PATH OUTPATH )
    set( multiValueArgs OUTPUT DEPENDS INCLUDE HEADER DEFINE OMNI_INCLUDE XMOD )

    cmake_parse_arguments( _PAR "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN} )

    set( _ARGS )

    if( NOT _PAR_MODE )
        ecbuild_critical( "No MODE specified for ${_func_name}()" )
    endif()
    list( APPEND _ARGS --mode ${_PAR_MODE} )

    _loki_transform_parse_args( loki_transform_convert )

    if( _PAR_CONFIG )
        list( APPEND _ARGS --config ${_PAR_CONFIG} )
    endif()

    if( _PAR_PATH )
        list( APPEND _ARGS --path ${_PAR_PATH} )
    endif()

    if( _PAR_OMNI_INCLUDE )
        foreach( _OMNI_INCLUDE ${_PAR_OMNI_INCLUDE} )
            list( APPEND _ARGS --omni-include ${_OMNI_INCLUDE} )
        endforeach()
    endif()

    if( ${_PAR_DATA_OFFLOAD} )
        list( APPEND _ARGS --data-offload )
    endif()

    if( ${_PAR_REMOVE_OPENMP} )
        list( APPEND _ARGS --remove-openmp )
    endif()

    add_custom_command(
        OUTPUT ${_PAR_OUTPUT}
        COMMAND ${_LOKI_TRANSFORM} convert ${_ARGS}
        DEPENDS ${_PAR_DEPENDS} ${_LOKI_TRANSFORM_DEPENDENCY}
        COMMENT "[Loki] Pre-processing: mode=${_PAR_MODE} frontend=${_PAR_FRONTEND}"
    )

endfunction()

##############################################################################
# .rst:
#
# loki_transform_transpile
# ========================
#
# Apply Loki transformation in transpile mode.::
#
#   loki_transform_transpile(
#       OUTPUT <outfile1> [<outfile2> ...]
#       DEPENDS <dependency1> [<dependency2> ...]
#       FRONTEND <frontend> [CPP]
#       [DRIVER <driver>]
#       [SOURCE <source1> [<source2> ...]]
#       [OUTPATH <outpath>]
#       [INCLUDE <include1> [<include2> ...]]
#       [HEADER <header1> [<header2> ...]]
#       [DEFINE <define1> [<define2> ...]]
#       [XMOD <xmod-dir1> [<xmod-dir2> ...]]
#   )
#
# Call ``loki-transform.py transpile ...`` with the provided arguments.
# See ``loki-transform.py`` for a description of all options.
#
# Options
# -------
#
# :OUTPUT:     The output files generated by Loki. Providing them here allows
#              to declare dependencies on this command later.
# :DEPENDS:    The input files or targets this call depends on.
#
##############################################################################

function( loki_transform_transpile )

    set( options CPP )
    set( oneValueArgs FRONTEND OUTPATH DRIVER )
    set( multiValueArgs OUTPUT DEPENDS SOURCE INCLUDE HEADER DEFINE XMOD )

    cmake_parse_arguments( _PAR "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN} )

    set( _ARGS )
    _loki_transform_parse_args( loki_transform_transpile )

    if( _PAR_SOURCE )
        foreach( _SRC ${_PAR_SOURCE} )
            list( APPEND _ARGS --source ${_SRC} )
        endforeach()
    endif()

    if( _PAR_DRIVER )
        list( APPEND _ARGS --driver ${_PAR_DRIVER} )
    endif()

    add_custom_command(
        OUTPUT ${_PAR_OUTPUT}
        COMMAND ${_LOKI_TRANSFORM} transpile ${_ARGS}
        DEPENDS ${_PAR_DEPENDS} ${_LOKI_TRANSFORM_DEPENDENCY}
        COMMENT "[Loki] Pre-processing: mode=transpile frontend=${_PAR_FRONTEND}"
    )

endfunction()


##############################################################################
# .rst:
#
# claw_compile
# ============
#
# Call the CLAW on a file.::
#
#   claw_compile(
#       OUTPUT <outfile>
#       SOURCE <source>
#       MODEL_CONFIG <config>
#       TARGET <cpu|gpu>
#       DIRECTIVE <openmp|openacc|none>
#       [INCLUDE <include1> [<include2> ...]]
#       [XMOD <xmod-dir1> [<xmod-dir2> ...]]
#       [DEPENDS <dependency1> [<dependency2> ...]]
#   )
#
##############################################################################
function( claw_compile )

    set( options )
    set( oneValueArgs MODEL_CONFIG TARGET DIRECTIVE SOURCE OUTPUT )
    set( multiValueArgs INCLUDE XMOD DEPENDS )

    cmake_parse_arguments( _PAR "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN} )

    if( NOT _PAR_SOURCE )
        ecbuild_critical( "No SOURCE given for claw_compile()" )
    endif()

    if( NOT _PAR_OUTPUT )
        ecbuild_critical( "No OUTPUT given for claw_compile()" )
    endif()

    set( _ARGS )

    if( _PAR_MODEL_CONFIG )
        list( APPEND _ARGS --model-config=${_PAR_MODEL_CONFIG})
    endif()

    if( NOT _PAR_TARGET )
        ecbuild_critical( "No TARGET given for claw_compile()" )
    endif()
    list( APPEND _ARGS --target=${_PAR_TARGET})

    if( NOT _PAR_DIRECTIVE )
        ecbuild_critical( "No TARGET given for claw_compile()" )
    endif()
    list( APPEND _ARGS --directive=${_PAR_DIRECTIVE})

    if( _PAR_INCLUDE )
        foreach( INCLUDE ${_PAR_INCLUDE} )
            list( APPEND _ARGS -I ${INCLUDE} )
        endforeach()
    endif()

    if( _PAR_XMOD )
        foreach( XMOD ${_PAR_XMOD} )
            list( APPEND _ARGS -J ${XMOD} )
        endforeach()
    endif()

    add_custom_command(
        OUTPUT ${_PAR_OUTPUT}
        COMMAND clawfc -w 132 ${_ARGS} -o ${_PAR_OUTPUT} ${_PAR_SOURCE}
        DEPENDS ${_PAR_SOURCE} ${_PAR_DEPENDS}
        COMMENT "[clawfc] Pre-processing: target=${_PAR_TARGET} directive=${_PAR_DIRECTIVE}"
    )

endfunction()


##############################################################################
# .rst:
#
# generate_xmod
# =============
#
# Call OMNI's F_Front on a file to generate its xml-parse tree and, as a
# side effect, xmod-file.::
#
#   generate_xmod(
#       OUTPUT <xml-file>
#       SOURCE <source>
#       [XMOD <xmod-dir1> [<xmod-dir2> ...]]
#       [DEPENDS <dependency1> [<dependency2> ...]]
#   )
#
# Note that the xmod-file will be located in the first path given to ``XMOD``.
#
##############################################################################
function( generate_xmod )

    set( options )
    set( oneValueArgs SOURCE OUTPUT )
    set( multiValueArgs XMOD DEPENDS )

    cmake_parse_arguments( _PAR "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN} )

    if( NOT _PAR_OUTPUT )
        ecbuild_critical( "No OUTPUT given for generate_xmod()" )
    endif()

    if( NOT _PAR_SOURCE )
        ecbuild_critical( "No SOURCE given for generate_xmod()" )
    endif()

    set( _ARGS )
    list( APPEND _ARGS -fleave-comment )

    if( _PAR_XMOD )
        foreach( XMOD ${_PAR_XMOD} )
            list( APPEND _ARGS -M ${XMOD} )
        endforeach()
    endif()

    if( TARGET clawfc )
        get_target_property( _CLAWFC_EXECUTABLE clawfc IMPORTED_LOCATION )
        get_filename_component( _CLAWFC_LOCATION ${_CLAWFC_EXECUTABLE} DIRECTORY )
        set( _F_FRONT_EXECUTABLE ${_CLAWFC_LOCATION}/F_Front )
        list( APPEND _PAR_DEPENDS clawfc )
    else()
        set( _F_FRONT_EXECUTABLE F_Front )
    endif()

    add_custom_command(
        OUTPUT ${_PAR_OUTPUT}
        COMMAND ${_F_FRONT_EXECUTABLE} ${_ARGS} -o ${_PAR_OUTPUT} ${_PAR_SOURCE}
        DEPENDS ${_PAR_SOURCE} ${_PAR_DEPENDS}
        COMMENT "[OMNI] Pre-processing: ${_PAR_SOURCE}"
    )

endfunction()
