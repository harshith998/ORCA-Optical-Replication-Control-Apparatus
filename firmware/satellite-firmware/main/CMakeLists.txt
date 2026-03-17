idf_component_register(
    SRCS "satellite-firmware.c"                  # ← match your actual filename
    INCLUDE_DIRS "."
    REQUIRES as7343 ulp
)

set(ulp_app_name lp_core_${COMPONENT_NAME})
set(ulp_lp_core_sources "lp_core/main.c")
set(ulp_exp_dep_srcs "satellite-firmware.c")     # ← the HP-core file that includes the generated header
ulp_embed_binary(${ulp_app_name} "${ulp_lp_core_sources}" "${ulp_exp_dep_srcs}")
