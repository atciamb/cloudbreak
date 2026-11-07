# Start ArduPlane SITL in WSL with Cloudbreak's Tutor-like parameters.
#   .\sim\sitl\run_sitl.ps1                    # instance 0, real time
#   .\sim\sitl\run_sitl.ps1 -Speedup 4 -Instance 1 -ExtraParm /mnt/c/cb-data/autoland/learned_landing.parm
# Ports (instance I adds 10*I): 5760 keeper (do not use), 5762 governor, 5763 core, 5765 QGC/relay.
param(
  [int]$Instance = 0,
  [double]$Speedup = 1,
  [string]$HomeLoc = "42.7303,-73.6798,68,0",
  [string]$ExtraParm = "",
  [switch]$KeepEeprom
)
$wipe = if ($KeepEeprom) { "0" } else { "1" }
wsl -d Ubuntu -- env SITL_INSTANCE=$Instance SITL_SPEEDUP=$Speedup SITL_HOME=$HomeLoc SITL_EXTRA_PARM=$ExtraParm SITL_WIPE=$wipe bash /mnt/c/dev/cloudbreak/sim/sitl/run_sitl.sh
