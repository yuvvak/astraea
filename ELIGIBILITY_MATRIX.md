# MA Eligibility Matrix

Generated from `alm/liabilities/eligibility_matrix.py`, which runs each row through the actual
`evaluate_eligibility` gate (`alm/liabilities/eligibility.py`). Regenerate with:

```bash
.venv/Scripts/python -c "from alm.liabilities.eligibility_matrix import render_markdown; print(render_markdown())" > ELIGIBILITY_MATRIX.md
```

| Product code | Scenario | Verdict | Reason | Citation |
|---|---|---|---|---|
| IND_ANNUITY_INPAY | baseline, no disqualifying features | eligible | product_code=IND_ANNUITY_INPAY meets MA 2.2 base eligibility conditions | MA 2.2 -- eligible individual/BPA annuity in payment, no future premiums, no disqualifying options |
| BPA_INPAY | baseline, no disqualifying features | eligible | product_code=BPA_INPAY meets MA 2.2 base eligibility conditions | MA 2.2 -- eligible individual/BPA annuity in payment, no future premiums, no disqualifying options |
| DEFERRED_ANNUITY | baseline, no disqualifying features | eligible | product_code=DEFERRED_ANNUITY meets MA 2.2 base eligibility conditions | MA 2.2 -- eligible individual/BPA annuity in payment, no future premiums, no disqualifying options |
| WP_GUARANTEED_ELEMENT | baseline, no disqualifying features | eligible_element | product_code=WP_GUARANTEED_ELEMENT is a recognised MA 2.3/2.5 eligible element | MA 2.3/2.5 -- eligible element of an otherwise ineligible contract |
| IP_INPAY | baseline, no disqualifying features | eligible_element | product_code=IP_INPAY is a recognised MA 2.3/2.5 eligible element | MA 2.3/2.5 -- eligible element of an otherwise ineligible contract |
| GROUP_DIS_DEPENDANT | baseline, no disqualifying features | eligible_element | product_code=GROUP_DIS_DEPENDANT is a recognised MA 2.3/2.5 eligible element | MA 2.3/2.5 -- eligible element of an otherwise ineligible contract |
| UNIT_LINKED | baseline | fail | product_code=UNIT_LINKED is explicitly excluded from the MA liability set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| FUTURE_PREMIUM_PAYING | baseline | fail | product_code=FUTURE_PREMIUM_PAYING is explicitly excluded from the MA liability set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| DISCRETIONARY_WITH_PROFITS | baseline | fail | product_code=DISCRETIONARY_WITH_PROFITS is explicitly excluded from the MA liability set | MA 2.3/2.5 -- with-profits contracts eligible only for the contractually guaranteed, non-discretionary component |
| UNKNOWN | baseline | fail | product_code is UNKNOWN / not on the MA-eligible product list | Not on the firm's MA-eligible product list (project brief scope) -- fails closed pending explicit classification |
| IND_ANNUITY_INPAY | plus future_premium_flag | fail | future_premium_flag is set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| IND_ANNUITY_INPAY | plus unit_linked_flag | fail | unit_linked_flag is set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| BPA_INPAY | plus future_premium_flag | fail | future_premium_flag is set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| BPA_INPAY | plus unit_linked_flag | fail | unit_linked_flag is set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| DEFERRED_ANNUITY | plus future_premium_flag | fail | future_premium_flag is set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| DEFERRED_ANNUITY | plus unit_linked_flag | fail | unit_linked_flag is set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| WP_GUARANTEED_ELEMENT | plus future_premium_flag | fail | future_premium_flag is set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| WP_GUARANTEED_ELEMENT | plus unit_linked_flag | fail | unit_linked_flag is set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| IP_INPAY | plus future_premium_flag | fail | future_premium_flag is set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| IP_INPAY | plus unit_linked_flag | fail | unit_linked_flag is set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| GROUP_DIS_DEPENDANT | plus future_premium_flag | fail | future_premium_flag is set | MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements |
| GROUP_DIS_DEPENDANT | plus unit_linked_flag | fail | unit_linked_flag is set | MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance) |
| WP_GUARANTEED_ELEMENT | plus discretionary_wp_flag (loses guaranteed-only status) | eligible_element | product_code=WP_GUARANTEED_ELEMENT is a recognised MA 2.3/2.5 eligible element | MA 2.3/2.5 -- eligible element of an otherwise ineligible contract |
| IND_ANNUITY_INPAY | plus discretionary_wp_flag | fail | discretionary_wp_flag is set on a non-guaranteed-element product | MA 2.3/2.5 -- with-profits contracts eligible only for the contractually guaranteed, non-discretionary component |
| DEFERRED_ANNUITY | plus surrender_option_flag, constrained (MA 2.2(4)(b) evidenced) | eligible | product_code=DEFERRED_ANNUITY meets MA 2.2 base eligibility conditions | MA 2.2 -- eligible individual/BPA annuity in payment, no future premiums, no disqualifying options |
| DEFERRED_ANNUITY | plus surrender_option_flag, unconstrained | fail | surrender_option_flag is set but constrained_surrender_flag is not -- MA 2.2(4)(b) condition (surrender value <= covering assets) is not evidenced | MA 2.2(4)(b) -- deferred annuity surrender/CETV/PCLS only eligible where surrender value <= value of covering assets at exercise |
| IND_ANNUITY_INPAY | plus surrender_option_flag (in-payment, no MA 2.2(4)(b) carve-out available) | fail | surrender_option_flag is set on a non-deferred product | MA 2.2 -- policyholder options other than the MA 2.2(4)(b)-constrained surrender are not MA-eligible |
