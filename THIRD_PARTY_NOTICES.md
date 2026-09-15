# Third-party notices and source availability

Updated 2026-09-15 for service 1.10.0 and the accompanying uv.lock.
The application is licensed under EUPL-1.2; see LICENSE. Dependencies retain their
own licenses and copyright notices. No ownership of third-party code is claimed.

## Python dependencies

See licenses.md and third_party_licenses/inventory.json for all 47 locked packages,
exact versions, source archive URLs/hashes, and copies of notices shipped by the
installed packages. The original license files are reproduced without modification.
The inventory includes development and Windows-only dependencies; not all are
installed in the production Linux image. Retain installed .dist-info directories,
source headers, notices, and this directory when redistributing dependencies.
The inventory's collection status is evidence coverage, not compliance approval.

**pyxroad 1.5.10:** its metadata and upstream README declare MIT, but the release
has no license/copyright file. The corresponding source tag also lacks that file:
https://github.com/AndreyShapovalovVN/pyxroad/tree/aed1635f858f3a13006aff629631e77d97379636
An authoritative complete notice must be obtained before claiming compliance.

**oots-lib 0.1.7:** the bundled LICENSE is EUPL-1.2. Source Python files accompany
the installed package in .venv/lib/python3.12/site-packages/oots_lib. The exact
source archive URL and SHA-256 are recorded in inventory.json. Retain the source
and license; offer recipients access when communicating its functionality.

**certifi 2026.7.22 and pathspec 1.1.1:** these components are covered by MPL-2.0.
Their editable Python sources (and certifi's certificate bundle) accompany their
installed packages; obtain complete release source archives through the exact
sdist URLs recorded in inventory.json. Modifications to their covered files must
remain under MPL-2.0. Preserve notices and make the corresponding source available
to recipients. pathspec is a development dependency.

**lxml 6.1.3:** retain LICENSE.txt and LICENSES.txt, and notices embedded in its
Python, schema and XSL files. Its binary wheels can include libraries with their
own terms, including LGPL-2.1 iconv. Package-level BSD labeling alone does not
establish compliance for the selected binary. See LICENSE_COMPLIANCE.md.

## Application source

Project repository:
https://github.com/AndreyShapovalovVN/EvidenceAuthorizationFromEIDAS

The container includes the application source at /app/main.py, /app/lib,
/app/Models, /app/static and /app/templates, plus its dependency/build manifests.
For network users, the operator must provide easily and freely accessible source
corresponding to the deployed revision, including modifications, and this license
information through the distribution/service channel. Merely naming a private
repository does not meet this requirement. No public accessibility verification
or deployment was performed by this audit.

## European Commission documentation

The following documents in docs/ are reproduced unchanged:

- eIDAS-Node Demo Tools Installation and Configuration Guide v3.0.0.
- eIDAS-Node National IdP and SP Integration Guide v3.0.0.

Source: European Commission, eIDAS-Node documentation. © European Union, 2023.
Their embedded reuse notices authorize reuse provided the source is acknowledged,
under Commission Decision 2011/833/EU. Their original notices remain in each PDF.
The software project's EUPL license does not replace these document notices.

## Container and build tools

Python, Debian packages, uv/uvx and native libraries carry separate licenses.
Retain /usr/share/doc/*/copyright and installed license/source notices. This
Python inventory is not an inventory of the entire container. See the release
requirements in LICENSE_COMPLIANCE.md before redistributing the image.
