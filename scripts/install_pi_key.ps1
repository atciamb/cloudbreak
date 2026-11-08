# Install the laptop's Cloudbreak SSH public key on the Pi (you type the Pi password once).
#   & .\scripts\install_pi_key.ps1 [-User pidrone] [-Target <ip or fe80::...%if>]
param(
  [string]$User = "pidrone",
  [string]$Target = ""
)
if (-not $Target) {
  $if = (Get-NetAdapter -Name "Ethernet 3").ifIndex
  $addr = (Resolve-DnsName raspberrypi.local -ErrorAction Stop | Where-Object { $_.IPAddress } | Select-Object -First 1).IPAddress
  if ($addr -like "fe80*") { $Target = "$addr%$if" } else { $Target = $addr }
}
$pub = (Get-Content "$env:USERPROFILE\.ssh\cloudbreak_pi.pub" -Raw).Trim()
$dataDir = if ($env:CLOUDBREAK_DATA) { $env:CLOUDBREAK_DATA } else { "C:\cb-data" }
$knownHosts = Join-Path $dataDir "keys\known_hosts_pi"
Write-Host "Installing key on $User@$Target -- enter the Pi password when asked." -ForegroundColor Cyan
ssh -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$knownHosts" "$User@$Target" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qxF '$pub' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys && echo KEY-INSTALLED"
