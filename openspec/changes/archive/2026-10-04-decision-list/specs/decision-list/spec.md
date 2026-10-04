## ADDED Requirements

### Requirement: Token-private lists

The system SHALL serve each list under `/l/<token>` where token is a cryptographically random 128-bit URL-safe string. Knowing the URL SHALL be the only authentication. The landing page SHALL offer list creation without any account, email, or password.

#### Scenario: Create a list

- **WHEN** a visitor submits the create form on the landing page
- **THEN** they are redirected to a unique `/l/<token>` URL that is their list

#### Scenario: Unknown token

- **WHEN** any `/l/<token>` URL with a nonexistent token is requested
- **THEN** the server responds 404 without revealing whether other tokens exist

### Requirement: Items and the 100-day deadline

A list owner SHALL add items (name required, price and URL optional). Each item SHALL get an immutable `decide_at` timestamp exactly 100 days after creation. The list page SHALL show, per item, the days remaining until `decide_at`. Items SHALL only be decidable (bought/dropped) or deletable by the list URL holder.

#### Scenario: Add an item

- **WHEN** an item named "ThinkPad X1" is added to a list
- **THEN** it appears on the list page with ~100 days remaining
- **AND** the stored `decide_at` minus `created_at` equals exactly 100 days

### Requirement: Decide and delete

The list page SHALL let the owner mark an item **bought** or **dropped**, or delete it. Decisions are final until the item is deleted; no history is kept (privacy: minimal data).

#### Scenario: Drop an item

- **WHEN** an item is decided "dropped"
- **THEN** the list page shows it as dropped with no countdown pressure

### Requirement: Privacy guarantees

The server SHALL use Python stdlib only (no third-party packages), set no cookies, perform no request logging (no access logs, no IPs persisted, no user agent retention), bind to 127.0.0.1 by default (override via `YAGNI_PORT`), and persist state to a single JSON file (`data/lists.json`) written atomically (temp file + rename). No data SHALL ever leave the server.

#### Scenario: No cookies or logs

- **WHEN** any sequence of requests is served
- **THEN** no response contains a Set-Cookie header and no log file is created

#### Scenario: State survives restart

- **WHEN** the server is restarted with the same `YAGNI_DATA` directory
- **THEN** all lists and items are still present
