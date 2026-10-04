# landing-site Specification

## Purpose
TBD - created by archiving change yagni-saas. Update Purpose after archive.
## Requirements
### Requirement: Single static page

The site SHALL consist of exactly one self-contained HTML document served at the root of `yagni.graphwiz.ai`, showing the YAGNI principle and a contact CTA.

#### Scenario: Visitor opens the site

- **WHEN** a visitor opens `https://yagni.graphwiz.ai/`
- **THEN** the page renders the headline "YAGNI", the expansion "You Aren't Gonna Need It", and a contact CTA — with no other interactive elements

### Requirement: Zero runtime dependencies

The page SHALL render fully with JavaScript disabled, SHALL make no network requests beyond the document itself (inline CSS, system fonts), and SHALL set no cookies and perform no tracking.

#### Scenario: Offline render

- **WHEN** the document is opened from the local filesystem with networking disabled
- **THEN** it renders completely (no external fetches, no broken resources)

### Requirement: Static deployability with fallback

The deployable artifact SHALL be exactly the set of static files in the repo root, requiring no build step, no server-side component, and no configuration. GitHub Pages (`gh-pages` branch) SHALL work as the documented fallback host.

#### Scenario: Deploy to any static host

- **WHEN** the repo root is uploaded to any static host as-is
- **THEN** the site works with no build or post-processing

#### Scenario: GitHub Pages fallback

- **WHEN** the repo's `gh-pages` branch is pushed and Pages is enabled
- **THEN** the site is served unchanged from that branch

### Requirement: Free and open source

The project SHALL be licensed under an OSI-approved license (MIT), contain only license-compatible original assets (system fonts, inline CSS), and depend on no proprietary runtime or service.

#### Scenario: License audit

- **WHEN** the repo is inspected
- **THEN** a `LICENSE` file exists and no file references proprietary assets or services

