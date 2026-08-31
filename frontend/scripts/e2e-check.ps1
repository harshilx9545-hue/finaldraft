# End-to-end check against the running backend.
# Windows PowerShell 5.1 compatible: no -SkipHttpErrorCheck, so failures are caught.
# Records the observed HTTP status for each step rather than inferring success.

$ErrorActionPreference = 'Continue'
$base = 'http://localhost:8000/api'
$origin = 'http://localhost:3000'
$results = New-Object System.Collections.ArrayList

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Path,
        [hashtable]$Body,
        [string]$Token
    )
    $headers = @{ Origin = $origin }
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    $params = @{
        Uri         = "$base$Path"
        Method      = $Method
        Headers     = $headers
        ContentType = 'application/json'
        UseBasicParsing = $true
    }
    if ($Body) { $params['Body'] = ($Body | ConvertTo-Json -Depth 6) }

    try {
        $response = Invoke-WebRequest @params
        $content = $null
        if ($response.Content) { $content = $response.Content | ConvertFrom-Json }
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $content; Cors = $response.Headers['Access-Control-Allow-Origin'] }
    } catch {
        $status = 0
        $content = $null
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $raw = $reader.ReadToEnd()
                if ($raw) { $content = $raw | ConvertFrom-Json }
            } catch {}
        }
        return [pscustomobject]@{ Status = $status; Body = $content; Cors = $null }
    }
}

function Record {
    param([string]$Step, [int]$Status, [int]$Expected, [string]$Detail)
    $ok = ($Status -eq $Expected)
    $null = $results.Add([pscustomobject]@{ Step = $Step; Status = $Status; Expected = $Expected; Pass = $ok; Detail = $Detail })
    $mark = if ($ok) { 'PASS' } else { 'FAIL' }
    Write-Output ("[{0}] {1} -> {2} (expected {3}) {4}" -f $mark, $Step, $Status, $Expected, $Detail)
}

$suffix = Get-Random -Maximum 999999
$ownerEmail = "owner$suffix@example.com"
$password = 'CorrectHorse99'

# --- 1. owner registration -------------------------------------------------
$reg = Invoke-Api -Method POST -Path '/auth/register/owner' -Body @{
    email = $ownerEmail; password = $password; password_confirm = $password
    business_name = "Gym $suffix"
    contact_phone = "+9199" + (Get-Random -Minimum 10000000 -Maximum 99999999)
}
Record 'POST /auth/register/owner' $reg.Status 201 ("gym=" + $reg.Body.gym.name + " role=" + $reg.Body.user.role)
Write-Output ("     CORS Access-Control-Allow-Origin: " + $reg.Cors)
$ownerToken = $reg.Body.tokens.access
$ownerRefresh = $reg.Body.tokens.refresh

# --- 2. login --------------------------------------------------------------
$login = Invoke-Api -Method POST -Path '/auth/login' -Body @{ identifier = $ownerEmail; password = $password }
Record 'POST /auth/login' $login.Status 200 ''
$ownerToken = $login.Body.access
$ownerRefresh = $login.Body.refresh

# --- 3. /api/me and the approved member_profile_id field --------------------
$me = Invoke-Api -Method GET -Path '/me' -Token $ownerToken
$keys = ($me.Body.PSObject.Properties.Name) -join ','
Record 'GET /me (owner)' $me.Status 200 ("role=" + $me.Body.role + " sub=" + $me.Body.subscription_status)
$hasField = $me.Body.PSObject.Properties.Name -contains 'member_profile_id'
Write-Output ("     /me keys: " + $keys)
Write-Output ("     member_profile_id present=" + $hasField + " value=" + $me.Body.member_profile_id + " (null for owner, as designed)")

# --- 4. owner overview counts ----------------------------------------------
$members0 = Invoke-Api -Method GET -Path '/members?page=1' -Token $ownerToken
Record 'GET /members' $members0.Status 200 ("count=" + $members0.Body.count)
$trainers0 = Invoke-Api -Method GET -Path '/trainers?page=1' -Token $ownerToken
Record 'GET /trainers' $trainers0.Status 200 ("count=" + $trainers0.Body.count)
$plans0 = Invoke-Api -Method GET -Path '/membership-plans?page=1' -Token $ownerToken
Record 'GET /membership-plans' $plans0.Status 200 ("count=" + $plans0.Body.count)
$invoices0 = Invoke-Api -Method GET -Path '/invoices?page=1' -Token $ownerToken
Record 'GET /invoices' $invoices0.Status 200 ("count=" + $invoices0.Body.count)
$gym0 = Invoke-Api -Method GET -Path '/gym' -Token $ownerToken
Record 'GET /gym' $gym0.Status 200 ("slug=" + $gym0.Body.slug)

# --- 5. creates -------------------------------------------------------------
$plan = Invoke-Api -Method POST -Path '/membership-plans' -Token $ownerToken -Body @{
    name = "Standard $suffix"; price = '1500.00'; duration_days = 30; currency = 'INR'
}
Record 'POST /membership-plans' $plan.Status 201 ("price=" + $plan.Body.price + " (string, as expected)")

$trainerEmail = "trainer$suffix@example.com"
$trainer = Invoke-Api -Method POST -Path '/trainers' -Token $ownerToken -Body @{
    email = $trainerEmail; first_name = 'Tara'; last_name = 'Iyer'; specialization = 'Strength'
}
Record 'POST /trainers' $trainer.Status 201 ("status=" + $trainer.Body.status)

$memberEmail = "member$suffix@example.com"
$member = Invoke-Api -Method POST -Path '/members' -Token $ownerToken -Body @{
    email = $memberEmail; join_date = (Get-Date).ToString('yyyy-MM-dd')
    first_name = 'Meera'; last_name = 'Rao'; goal = 'strength'
    plan = $plan.Body.id; trainer = $trainer.Body.id
}
Record 'POST /members' $member.Status 201 ("is_active=" + $member.Body.is_active + " (false: no membership route exists)")
$memberId = $member.Body.id

# --- 6. updates -------------------------------------------------------------
$patchMember = Invoke-Api -Method PATCH -Path "/members/$memberId" -Token $ownerToken -Body @{ goal = 'bulk' }
Record "PATCH /members/$memberId" $patchMember.Status 200 ("goal=" + $patchMember.Body.goal)

$patchGym = Invoke-Api -Method PATCH -Path '/gym' -Token $ownerToken -Body @{ name = "Gym $suffix Renamed" }
Record 'PATCH /gym' $patchGym.Status 200 ("name=" + $patchGym.Body.name)

# --- 7. existence non-disclosure -------------------------------------------
$nonexistent = Invoke-Api -Method GET -Path '/members/99999999' -Token $ownerToken
Record 'GET /members/99999999 (no such record)' $nonexistent.Status 404 ("code=" + $nonexistent.Body.error.code)

# A second gym, to prove another tenant's real id is indistinguishable from the above.
$suffix2 = Get-Random -Maximum 999999
$reg2 = Invoke-Api -Method POST -Path '/auth/register/owner' -Body @{
    email = "owner$suffix2@example.com"; password = $password; password_confirm = $password
    business_name = "Other Gym $suffix2"
    contact_phone = "+9198" + (Get-Random -Minimum 10000000 -Maximum 99999999)
}
Record 'POST /auth/register/owner (second gym)' $reg2.Status 201 ''
$otherToken = $reg2.Body.tokens.access
$otherMember = Invoke-Api -Method POST -Path '/members' -Token $otherToken -Body @{
    email = "other$suffix2@example.com"; join_date = (Get-Date).ToString('yyyy-MM-dd')
}
Record 'POST /members (second gym)' $otherMember.Status 201 ''
$crossTenant = Invoke-Api -Method GET -Path ("/members/" + $otherMember.Body.id) -Token $ownerToken
Record 'GET another gym member id (as gym 1 owner)' $crossTenant.Status 404 ("code=" + $crossTenant.Body.error.code)
$identical = ($crossTenant.Status -eq $nonexistent.Status) -and ($crossTenant.Body.error.code -eq $nonexistent.Body.error.code)
Write-Output ("     cross-tenant 404 identical to nonexistent 404: " + $identical)

# --- 8. role gating --------------------------------------------------------
$trainerAsOwnerCheck = Invoke-Api -Method GET -Path '/trainers?page=1' -Token $otherToken
Record 'GET /trainers (other owner, own gym)' $trainerAsOwnerCheck.Status 200 ''

# --- 9. invoices and payment ----------------------------------------------
$invoices1 = Invoke-Api -Method GET -Path '/invoices?page=1' -Token $ownerToken
Record 'GET /invoices (after registration)' $invoices1.Status 200 ("count=" + $invoices1.Body.count)
if ($invoices1.Body.count -gt 0) {
    $open = $invoices1.Body.results | Where-Object { $_.status -eq 'open' } | Select-Object -First 1
    if ($open) {
        Write-Output ("     invoice " + $open.number + " total=" + $open.total_amount + " cgst=" + $(if ($null -eq $open.cgst) { 'null (tax not applicable)' } else { $open.cgst }))
        $pay = Invoke-Api -Method POST -Path ("/invoices/" + $open.id + "/pay") -Token $ownerToken -Body @{}
        Record ("POST /invoices/" + $open.id + "/pay") $pay.Status 201 ("order_ref set=" + [bool]$pay.Body.order_ref + " amount_minor=" + $pay.Body.amount_minor)
        $after = Invoke-Api -Method GET -Path ("/invoices/" + $open.id) -Token $ownerToken
        Write-Output ("     invoice status after pay: " + $after.Body.status + " (settles only via gateway webhook - NOT verified here)")
    }
}

# --- 10. card data rejection ----------------------------------------------
if ($invoices1.Body.count -gt 0) {
    $anyInvoice = $invoices1.Body.results | Select-Object -First 1
    $card = Invoke-Api -Method POST -Path ("/invoices/" + $anyInvoice.id + "/pay") -Token $ownerToken -Body @{ card_number = '4111111111111111' }
    Record 'POST pay with a card field (must be refused)' $card.Status 400 ("code=" + $card.Body.error.code)
}

# --- 11. member session via password reset --------------------------------
$reset = Invoke-Api -Method POST -Path '/auth/password-reset' -Body @{ email = $memberEmail }
Record 'POST /auth/password-reset (member)' $reset.Status 202 ''

# --- 12. logout ------------------------------------------------------------
$logout = Invoke-Api -Method POST -Path '/auth/logout' -Token $ownerToken -Body @{ refresh = $ownerRefresh }
Record 'POST /auth/logout' $logout.Status 204 ''
$afterLogout = Invoke-Api -Method POST -Path '/auth/refresh' -Body @{ refresh = $ownerRefresh }
Record 'POST /auth/refresh with a blacklisted token' $afterLogout.Status 401 ("code=" + $afterLogout.Body.error.code)

# --- 13. no DELETE anywhere ----------------------------------------------
$del = Invoke-Api -Method DELETE -Path "/members/$memberId" -Token $login.Body.access
Write-Output ("[INFO] DELETE /members/$memberId -> " + $del.Status + " (no route accepts DELETE)")

# --- summary --------------------------------------------------------------
Write-Output ''
Write-Output '================ SUMMARY ================'
$passed = ($results | Where-Object { $_.Pass }).Count
$total = $results.Count
Write-Output ("$passed / $total checks matched the expected status")
$results | Where-Object { -not $_.Pass } | ForEach-Object {
    Write-Output ("  MISMATCH: " + $_.Step + " got " + $_.Status + " expected " + $_.Expected)
}
Write-Output ("MEMBER_EMAIL=" + $memberEmail)
Write-Output ("TRAINER_EMAIL=" + $trainerEmail)
