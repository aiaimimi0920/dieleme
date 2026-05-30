param(
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath
)

function Test-HasText {
    param(
        [AllowNull()]
        [object]$Value
    )

    return -not [string]::IsNullOrWhiteSpace([string]$Value)
}

function Test-KnownText {
    param(
        [AllowNull()]
        [object]$Value
    )

    return (Test-HasText $Value) -and ([string]$Value -ne "unknown")
}

try {
    $j = Get-Content -Raw -LiteralPath $SummaryPath | ConvertFrom-Json

    $source = [string]$j.operator_escalation_source
    $suggestedMode = [string]$j.lifecycle_suggested_mode
    $actionHint = [string]$j.operator_action_hint
    $resolvedActionHint = if (Test-KnownText $actionHint) { $actionHint } else { "" }
    if (-not (Test-KnownText $resolvedActionHint)) {
        if ($source -eq "lifecycle_high_priority_backlog") {
            $resolvedActionHint = "inspect unresolved high-priority backlog"
            if (Test-KnownText $suggestedMode) {
                $resolvedActionHint += "; suggested mode=$suggestedMode"
            }
        }
        elseif ($source -eq "recovery_policy") {
            $resolvedActionHint = "follow recovery policy escalation guidance"
            if (Test-KnownText $suggestedMode) {
                $resolvedActionHint += "; suggested mode=$suggestedMode"
            }
        }
    }

    $auditMessage = [string]$j.operator_escalation_audit_message
    $hasAudit = Test-KnownText $auditMessage
    $hasResolvedActionHint = Test-KnownText $resolvedActionHint
    $actionHintCarriesSuggestedMode = (Test-KnownText $suggestedMode) -and (Test-KnownText $resolvedActionHint) -and ($resolvedActionHint -match ("suggested mode=" + [regex]::Escape($suggestedMode)))
    $effectiveMode = [string]$j.effective_mode
    $effectiveModeCoveredByActionHint = (Test-HasText $effectiveMode) -and $actionHintCarriesSuggestedMode -and ($effectiveMode -eq $suggestedMode)
    $sourceCoveredByActionHint = ($source -eq "recovery_policy") -and (Test-KnownText $resolvedActionHint) -and ($resolvedActionHint -match "recovery policy")

    $interventionStatus = [string]$j.intervention_status
    $interventionStabilityActionHint = [string]$j.intervention_stability_action_hint
    $interventionReason = [string]$j.intervention_reason
    $interventionStabilityStatus = [string]$j.intervention_stability_status
    $interventionStabilityExplanation = [string]$j.intervention_stability_explanation
    $interventionStatusCoveredByExplanation = (Test-HasText $interventionStatus) -and (Test-HasText $interventionStabilityExplanation) -and ($interventionStabilityExplanation -match [regex]::Escape($interventionStatus))

    $escalationReason = [string]$j.top_policy_reason
    $digestStatus = [string]$j.operator_digest_status
    $digestMessage = [string]$j.operator_digest_message
    $digestStabilityStatus = [string]$j.operator_digest_stability_status
    $sourceCurrent = [string]$j.operator_escalation_current_source
    $sourcePrevious = [string]$j.operator_escalation_previous_source
    $sourceStabilityStatus = [string]$j.operator_escalation_source_stability_status
    $sourceStabilityExplanation = [string]$j.operator_escalation_source_stability_explanation
    $finalGuidanceMessage = [string]$j.operator_final_guidance_message

    $digestStatusCoveredByAudit = $hasAudit -and (Test-HasText $digestStatus) -and $auditMessage.Contains("digest=$digestStatus")
    $digestMessageCoveredByAudit = $hasAudit -and (Test-HasText $digestMessage) -and $auditMessage.Contains($digestMessage)
    $digestStabilityCoveredByAudit = $hasAudit -and (Test-HasText $digestStabilityStatus) -and $auditMessage.Contains("digest_stability=$digestStabilityStatus")
    $digestMessageCoveredByFinalGuidance = (-not $hasAudit) -and (Test-HasText $digestMessage) -and ($digestMessage -eq $finalGuidanceMessage)

    if (Test-KnownText $digestStatus) {
        if (-not $digestStatusCoveredByAudit) {
            Write-Host "[WARN] Operator digest status: $digestStatus"
        }
    }
    if (Test-KnownText $j.operator_digest_priority) {
        Write-Host ("[WARN] Operator digest priority: " + [string]$j.operator_digest_priority)
    }
    if (Test-KnownText $digestMessage) {
        if (-not ($digestMessageCoveredByAudit -or $digestMessageCoveredByFinalGuidance)) {
            Write-Host "[WARN] Operator digest: $digestMessage"
        }
    }
    if (Test-KnownText $digestStabilityStatus) {
        if (-not $digestStabilityCoveredByAudit) {
            Write-Host "[WARN] Operator digest stability: $digestStabilityStatus"
        }
    }
    if (Test-KnownText $j.operator_digest_stability_severity) {
        Write-Host ("[WARN] Operator digest stability severity: " + [string]$j.operator_digest_stability_severity)
    }
    if (Test-KnownText $j.operator_digest_stability_explanation) {
        Write-Host ("[WARN] Operator digest stability explanation: " + [string]$j.operator_digest_stability_explanation)
    }
    if (Test-KnownText $j.operator_final_guidance_message) {
        if (-not $hasAudit) {
            Write-Host ("[WARN] Operator final guidance: " + [string]$j.operator_final_guidance_message)
        }
    }
    if ($hasAudit) {
        Write-Host "[WARN] Operator escalation audit: $auditMessage"
    }
    if (Test-KnownText $sourceCurrent) {
        if (-not (Test-KnownText $sourceStabilityExplanation)) {
            Write-Host "[WARN] Operator escalation current source: $sourceCurrent"
        }
    }
    if (Test-KnownText $sourcePrevious) {
        if (-not (Test-KnownText $sourceStabilityExplanation)) {
            Write-Host "[WARN] Operator escalation previous source: $sourcePrevious"
        }
    }
    if (Test-KnownText $j.operator_escalation_source_change_count) {
        Write-Host ("[WARN] Operator escalation source change count: " + [string]$j.operator_escalation_source_change_count)
    }
    if (Test-KnownText $j.operator_escalation_source_last_changed_at) {
        Write-Host ("[WARN] Operator escalation source last changed at: " + [string]$j.operator_escalation_source_last_changed_at)
    }
    if (Test-KnownText $sourceStabilityStatus) {
        if (-not (Test-KnownText $sourceStabilityExplanation)) {
            Write-Host "[WARN] Operator escalation source stability: $sourceStabilityStatus"
        }
    }
    if (Test-KnownText $j.operator_escalation_source_stability_severity) {
        Write-Host ("[WARN] Operator escalation source stability severity: " + [string]$j.operator_escalation_source_stability_severity)
    }
    if (Test-KnownText $j.operator_escalation_source_stability_explanation) {
        Write-Host ("[WARN] Operator escalation source stability explanation: " + [string]$j.operator_escalation_source_stability_explanation)
    }
    if (Test-KnownText $j.operator_escalation_source) {
        if ((-not $hasAudit) -and (-not $sourceCoveredByActionHint)) {
            Write-Host "[WARN] Operator escalation source: $source"
        }
    }
    if (Test-KnownText $j.effective_mode) {
        if (-not $effectiveModeCoveredByActionHint) {
            Write-Host ("[WARN] Operator escalation effective mode: " + [string]$j.effective_mode)
        }
    }
    if (Test-KnownText $j.top_policy_reason) {
        if (-not $hasAudit) {
            Write-Host ("[WARN] Operator escalation reason: " + [string]$j.top_policy_reason)
        }
    }
    if (Test-KnownText $interventionStatus) {
        if (-not $interventionStatusCoveredByExplanation) {
            Write-Host "[WARN] Operator intervention status: $interventionStatus"
        }
    }
    if (Test-KnownText $j.intervention_priority) {
        Write-Host ("[WARN] Operator intervention priority: " + [string]$j.intervention_priority)
    }
    if (Test-KnownText $interventionReason) {
        if ($hasAudit -or ($interventionReason -ne $escalationReason)) {
            Write-Host "[WARN] Operator intervention reason: $interventionReason"
        }
    }
    if (Test-KnownText $interventionStabilityStatus) {
        if (-not (Test-KnownText $interventionStabilityExplanation)) {
            Write-Host "[WARN] Operator intervention stability: $interventionStabilityStatus"
        }
    }
    if (Test-KnownText $j.intervention_stability_severity) {
        Write-Host ("[WARN] Operator intervention stability severity: " + [string]$j.intervention_stability_severity)
    }
    if (Test-KnownText $j.intervention_stability_explanation) {
        Write-Host ("[WARN] Operator intervention stability explanation: " + [string]$j.intervention_stability_explanation)
    }
    if (Test-KnownText $interventionStabilityActionHint) {
        if ($interventionStabilityActionHint -ne $resolvedActionHint) {
            Write-Host "[WARN] Operator intervention stability action hint: $interventionStabilityActionHint"
        }
    }
    if (Test-KnownText $j.lifecycle_follow_up) {
        if (-not $hasResolvedActionHint) {
            Write-Host ("[WARN] Operator follow-up: " + [string]$j.lifecycle_follow_up)
        }
    }
    if (Test-KnownText $j.lifecycle_suggested_mode) {
        if (-not $actionHintCarriesSuggestedMode) {
            Write-Host ("[WARN] Operator suggested mode: " + $suggestedMode)
        }
    }
    if (Test-KnownText $resolvedActionHint) {
        Write-Host "[WARN] Operator action hint: $resolvedActionHint"
    }
}
catch {}
