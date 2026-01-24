indicators = {
    "p_pmd": 600, # Marginal day-ahead market price.
    "p_pmi1":612, # Marginal within-day seshion 1 market price.
    "p_pmi2":613, # Marginal within-day seshion 2 market price.
    "p_pmi3":614, # Marginal within-day seshion 3 market price.
    "p_pmi4":615, # Marginal within-day seshion 4 market price.
    "p_pmi5":616, # Marginal within-day seshion 5 market price.
    "p_pmi6":617, # Marginal within-day seshion 6 market price.
    "p_pmi7":618, # Marginal within-day seshion 7 market price.
    "p_afrr_up":2130, # aFRR up reserve price.
    "p_afrr_down":634, # aFRR down reserve price.
    "p_afrr_act_up":682, # aFRR up activation price.
    "p_afrr_act_down":683, # aFRR down activation price.

    "e_pmd":602, # Energy traded, day-ahead.
    "e_pmi1":605, # Energy traded, within-day seshion 1.
    "e_pmi2":606, # Energy traded, within-day seshion 2.
    "e_pmi3":607, # Energy traded, within-day seshion 3.
    "e_pmi4":608, # Energy traded, within-day seshion 4.
    "e_pmi5":609, # Energy traded, within-day seshion 5.
    "e_pmi6":610, # Energy traded, within-day seshion 6.
    "e_pmi7":611, # Energy traded, within-day seshion 7.
    "band_afrr_up":632, # aFRR up allocated energy.
    "band_afrr_down":633, # aFRR down allocated energy.
    "e_afrr_act_up":680, # aFRR up energy activation.
    "e_afrr_act_down":681, # aFRR down energy activation.
}

archives = {
    "uf":110,
    "up":111,
    "brp":112,
    "entitled_participants":113,
}

def common_indicators(value):
    if isinstance(value, str):
        value = indicators[value]
    return value

def common_archives(value):
    if isinstance(value, str):
        value = archives[value]
    return value