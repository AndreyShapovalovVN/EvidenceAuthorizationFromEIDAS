# Ліцензії компонентів

Аудит 2026-09-15; версії звірено з `uv.lock`. Таблиця охоплює runtime, dev та платформні залежності.
Повні повідомлення: [third_party_licenses](third_party_licenses/); докази й SHA-256: [inventory.json](third_party_licenses/inventory.json).
Висновки та невиконані умови: [LICENSE_COMPLIANCE.md](LICENSE_COMPLIANCE.md).

| Name               | Version   | License                              |
|--------------------|-----------|--------------------------------------|
| Jinja2             | 3.1.6     | BSD License                          |
| MarkupSafe         | 3.0.3     | BSD-3-Clause                         |
| Pygments           | 2.21.0    | BSD-2-Clause                         |
| annotated-doc      | 0.0.5     | MIT                                  |
| annotated-types    | 0.8.0     | MIT                                  |
| anyio              | 4.15.1    | MIT                                  |
| ast_serialize      | 0.11.0    | MIT                                  |
| attrs              | 26.1.0    | MIT                                  |
| certifi            | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| charset-normalizer | 3.5.1     | MIT                                  |
| click              | 8.5.0     | BSD-3-Clause                         |
| fastapi            | 0.141.1   | MIT                                  |
| h11                | 0.16.0    | MIT License                          |
| httpcore           | 1.0.9     | BSD-3-Clause                         |
| httpx              | 0.28.1    | BSD License                          |
| idna               | 3.19      | BSD-3-Clause                         |
| iniconfig          | 2.3.0     | MIT                                  |
| isodate            | 0.7.2     | BSD License                          |
| librt              | 0.15.0    | MIT                                  |
| lxml               | 6.1.3     | BSD-3-Clause                         |
| mypy               | 2.3.1     | MIT                                  |
| mypy_extensions    | 1.1.0     | MIT                                  |
| oots-lib           | 0.1.7     | EUPL-1.2 (bundled LICENSE)            |
| packaging          | 26.3      | Apache-2.0 OR BSD-2-Clause           |
| pathspec           | 1.1.1     | Mozilla Public License 2.0 (MPL 2.0) |
| platformdirs       | 4.11.7    | MIT                                  |
| pluggy             | 1.6.0     | MIT License                          |
| pyRegRep           | 15        | MIT                                  |
| pydantic           | 2.13.5    | MIT                                  |
| pydantic_core      | 2.46.5    | MIT                                  |
| pytest             | 9.1.1     | MIT                                  |
| python-multipart   | 0.0.32    | Apache-2.0                           |
| pyxroad            | 1.5.10    | MIT License                          |
| redis              | 8.1.0     | MIT                                  |
| requests           | 2.34.2    | Apache Software License              |
| requests-file      | 3.0.1     | Apache Software License              |
| requests-toolbelt  | 1.0.0     | Apache Software License              |
| ruff               | 0.16.7    | MIT                                  |
| starlette          | 1.6.0     | BSD-3-Clause                         |
| typing-inspection  | 0.4.4     | MIT                                  |
| typing_extensions  | 4.16.0    | PSF-2.0                              |
| urllib3            | 2.7.0     | MIT                                  |
| uvicorn            | 0.52.4    | BSD-3-Clause                         |
| xmltodict          | 1.0.4     | MIT                                  |
| zeep               | 4.3.3     | MIT License                          |
| colorama           | 0.4.6     | BSD-3-Clause (Windows dependency)     |
| setuptools         | 84.0.0    | MIT; vendored notices retained        |

`pyxroad`: MIT задекларовано, але текст ліцензії та copyright відсутні в релізі; питання не закрито.
`lxml`: BSD стосується основного пакета; вкладені компоненти мають додаткові умови, див. LICENSES.txt та звіт.
