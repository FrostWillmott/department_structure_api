# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/FrostWillmott/department_structure_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                         |    Stmts |     Miss |   Cover |   Missing |
|----------------------------- | -------: | -------: | ------: | --------: |
| app/\_\_init\_\_.py          |        0 |        0 |    100% |           |
| app/config.py                |        7 |        0 |    100% |           |
| app/database.py              |       10 |        0 |    100% |           |
| app/error\_handlers.py       |       14 |        0 |    100% |           |
| app/exceptions.py            |       25 |        0 |    100% |           |
| app/models.py                |       22 |        0 |    100% |           |
| app/routers/\_\_init\_\_.py  |        0 |        0 |    100% |           |
| app/routers/departments.py   |       22 |        3 |     86% |38, 109, 146 |
| app/routers/employees.py     |       11 |        1 |     91% |        33 |
| app/schemas.py               |       53 |        0 |    100% |           |
| app/services/\_\_init\_\_.py |        0 |        0 |    100% |           |
| app/services/\_pg.py         |       13 |        0 |    100% |           |
| app/services/departments.py  |      128 |       44 |     66% |50-52, 70, 77, 85, 94-100, 137-169, 192, 199, 202, 205, 237-238, 249-272 |
| app/services/employees.py    |       23 |        4 |     83% |19, 30, 38-39 |
| **TOTAL**                    |  **328** |   **52** | **84%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/FrostWillmott/department_structure_api/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/FrostWillmott/department_structure_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FrostWillmott/department_structure_api/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/FrostWillmott/department_structure_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FFrostWillmott%2Fdepartment_structure_api%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/FrostWillmott/department_structure_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.