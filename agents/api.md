# TokenScribe — API Contracts

## Studies

```
GET  /studies                    list all studies
GET  /studies/new                form to create study
POST /studies/new                create study
GET  /studies/<id>               study detail
GET  /studies/<id>/edit          edit form
POST /studies/<id>/edit          update study
POST /studies/<id>/delete        delete study
```

## Prompts

```
GET  /studies/<id>/prompts       list prompts for study
GET  /studies/<id>/prompts/new   form to add prompt
POST /studies/<id>/prompts/new   create prompt
GET  /prompts/<id>               prompt detail with translations
GET  /prompts/<id>/edit          edit form
POST /prompts/<id>/edit          update prompt
POST /prompts/<id>/delete        delete prompt
```

## Translations

```
GET  /prompts/<id>/translations              list candidates
GET  /prompts/<id>/translations/new          form to add candidate
POST /prompts/<id>/translations/new          create candidate
POST /translations/<id>/score                compute SFS for candidate
POST /translations/<id>/approve              approve candidate
POST /translations/<id>/reject               reject candidate
GET  /prompts/<id>/translations/compare      side-by-side comparison view
```

## Experiments

```
GET  /experiments                            list all runs
GET  /studies/<id>/experiments/new          form to configure run
POST /studies/<id>/experiments/run          execute experiment run
GET  /experiments/<id>                      run detail + token results
GET  /experiments/<id>/pei                  PEI results for run
```

## Settings

```
GET  /settings                   settings dashboard
POST /settings/api-keys          save API keys
POST /settings/models            update model list / cost config
POST /settings/reset-db          reset database (with confirmation)
```

## Reports

```
GET  /reports                    reports dashboard
GET  /reports/export/csv         export token_results as CSV
GET  /reports/export/json        export full dataset as JSON
GET  /reports/scores             SFS/PEI visualization page
GET  /studies/<id>/report        per-study report
```
