# Input contract: macOS `ps -axo pid=,ucomm=,args=`.
#
# Only a Python executable running the exact 15m daemon entry point is a live
# duplicate. Shell/orchestrator command lines may contain the same text while
# compiling, inspecting or restarting the daemon; their ucomm is not Python and
# must not block launchd startup.
$2 ~ /^python([0-9]+([.][0-9]+)*)?$/ {
    if ($0 ~ /(^|[[:space:]])scripts\/futures_daemon_v14[.]py([[:space:]]|$)/) {
        if ($0 ~ /(^|[[:space:]])--timeframe[[:space:]]+15m([[:space:]]|$)/) {
            print $1
            exit
        }
    }
}
