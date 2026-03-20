def calculate_weekly_split(worked_min: int, week_limit_min: int, is_sick_or_absent: bool = False):
    """
    Weekly split into contract and overtime minutes.
    """
    if is_sick_or_absent:
        contract_min = worked_min
        overtime_min = 0
    else:
        contract_min = min(worked_min, week_limit_min)
        overtime_min = max(0, worked_min - week_limit_min)
        
    return {
        "contract_min": contract_min,
        "overtime_min": overtime_min
    }

def calculate_monthly_total(weekly_splits: list, adjustments_min: int = 0):
    """
    Sum weeks + apply monthly_adjustments.
    DATEV gets CONTRACT only, not OVERTIME.
    """
    total_contract = sum(split.get("contract_min", 0) for split in weekly_splits)
    total_overtime = sum(split.get("overtime_min", 0) for split in weekly_splits)
    
    # Apply adjustments
    total_contract += adjustments_min
    
    return {
        "contract_min": max(0, total_contract),
        "overtime_min": total_overtime
    }
