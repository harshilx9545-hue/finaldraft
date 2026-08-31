# Verifies the registration password contract against the running backend.
#
# The frontend bug was that a failed registration emptied the password field. These
# checks confirm the payload the frontend builds is what the backend expects, that a
# password rejection is reported against the password field (so the UI can attach it),
# and that the account created is genuinely usable with the password that was typed.

$ErrorActionPreference = 'Continue'
$base = 'http://localhost:8000/api'
$origin = 'http://localhost:3000'

function Invoke-Api {
    param([string]$Method, [string]$Path, [hashtable]$Body, [string]$Token)
    $headers = @{ Origin = $origin }
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    $params = @{
        Uri = "$base$Path"; Method = $Method; Headers = $headers
        ContentType = 'application/json'; UseBasicParsing = $true
    }
    if ($Body) { $params['Body'] = ($Body | ConvertTo-Json -Depth 6) }
    try {
        $r = Invoke-WebRequest @params
        $c = $null; if ($r.Content) { $c = $r.Content | ConvertFrom-Json }
        return [pscustomobject]@{ Status = [int]$r.StatusCode; Body = $c }
    } catch {
        $status = 0; $c = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        # Windows PowerShell 5.1 puts the error response body here. Reading
        # GetResponseStream() instead returns nothing, because it has already been
        # consumed by the time the exception surfaces.
        $raw = $_.ErrorDetails.Message
        if (-not $raw -and $_.Exception.Response) {
            try {
                $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $raw = $sr.ReadToEnd()
            } catch {}
        }
        if ($raw) { try { $c = $raw | ConvertFrom-Json } catch {} }
        return [pscustomobject]@{ Status = $status; Body = $c }
    }
}

# Registration is throttled at 5/min per IP, and this script makes four attempts on
# purpose. Clearing the throttle cache between them keeps the checks independent
# instead of turning the later ones into 429s.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
function Reset-Throttle {
    $py = Join-Path $repoRoot '.venv\Scripts\python.exe'
    & $py (Join-Path $repoRoot 'manage.py') shell -c "from django.core.cache import cache; cache.clear()" 2>&1 | Out-Null
}

$pass = 0; $total = 0
function Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $script:total++
    if ($Ok) { $script:pass++ }
    Write-Output ("[{0}] {1} {2}" -f $(if ($Ok) { 'PASS' } else { 'FAIL' }), $Name, $Detail)
}

$suffix = Get-Random -Maximum 999999
$email = "pwcheck$suffix@example.com"
# Deliberately contains a trailing space: the backend declares trim_whitespace=False
# on both password fields, so the frontend must not trim it either.
$password = 'CorrectHorse99 '
$phone = "+9197" + (Get-Random -Minimum 10000000 -Maximum 99999999)

Write-Output "=== 1. password is accepted verbatim, including trailing whitespace ==="
Reset-Throttle
$reg = Invoke-Api -Method POST -Path '/auth/register/owner' -Body @{
    email = $email; password = $password; password_confirm = $password
    business_name = "PW Gym $suffix"; contact_phone = $phone
}
Check 'registration succeeds' ($reg.Status -eq 201) "status=$($reg.Status)"

Write-Output ''
Write-Output "=== 2. login with the exact password that was typed ==="
Reset-Throttle
$login = Invoke-Api -Method POST -Path '/auth/login' -Body @{ identifier = $email; password = $password }
Check 'login succeeds with the same password' ($login.Status -eq 200) "status=$($login.Status)"
$me = Invoke-Api -Method GET -Path '/me' -Token $login.Body.access
Check 'session resolves to the new owner' (($me.Status -eq 200) -and ($me.Body.role -eq 'owner')) "role=$($me.Body.role)"

Write-Output ''
Write-Output "=== 3. a trimmed password must NOT authenticate (proves no trimming) ==="
$trimmed = Invoke-Api -Method POST -Path '/auth/login' -Body @{ identifier = $email; password = $password.Trim() }
Check 'trimmed password is rejected' ($trimmed.Status -eq 401) "status=$($trimmed.Status) code=$($trimmed.Body.error.code)"

Write-Output ''
Write-Output "=== 4. a password rejection names the password field ==="
# 'password' is on Django's common-password list, so this is refused server-side even
# though it satisfies the client's length rule.
Reset-Throttle
$weak = Invoke-Api -Method POST -Path '/auth/register/owner' -Body @{
    email = "weak$suffix@example.com"; password = 'password12'; password_confirm = 'password12'
    business_name = "Weak Gym $suffix"; contact_phone = "+9196" + (Get-Random -Minimum 10000000 -Maximum 99999999)
}
Check 'weak password refused with 400' ($weak.Status -eq 400) "status=$($weak.Status)"
Check 'error names the password field' ($weak.Body.error.details.field -eq 'password') "field=$($weak.Body.error.details.field) code=$($weak.Body.error.code)"
Write-Output ("     message: " + $weak.Body.error.message)

Write-Output ''
Write-Output "=== 5. a mismatch is reported against password_confirm ==="
Reset-Throttle
$mismatch = Invoke-Api -Method POST -Path '/auth/register/owner' -Body @{
    email = "mm$suffix@example.com"; password = 'CorrectHorse99'; password_confirm = 'DifferentHorse99'
    business_name = "MM Gym $suffix"; contact_phone = "+9195" + (Get-Random -Minimum 10000000 -Maximum 99999999)
}
Check 'mismatch refused with 400' ($mismatch.Status -eq 400) "status=$($mismatch.Status)"
Check 'error names password_confirm' ($mismatch.Body.error.details.field -eq 'password_confirm') "field=$($mismatch.Body.error.details.field)"

Write-Output ''
Write-Output "=== 6. a duplicate email is reported against email, not password ==="
# This is the case that used to wipe the password field for no reason.
Reset-Throttle
$dup = Invoke-Api -Method POST -Path '/auth/register/owner' -Body @{
    email = $email; password = 'AnotherHorse99'; password_confirm = 'AnotherHorse99'
    business_name = "Dup Gym $suffix"; contact_phone = "+9194" + (Get-Random -Minimum 10000000 -Maximum 99999999)
}
Check 'duplicate email refused with 400' ($dup.Status -eq 400) "status=$($dup.Status)"
Check 'error names email, so password must be preserved' ($dup.Body.error.details.field -eq 'email') "field=$($dup.Body.error.details.field)"

Write-Output ''
Write-Output "======================================="
Write-Output "$pass / $total checks passed"
Write-Output "REGISTERED_EMAIL=$email"
