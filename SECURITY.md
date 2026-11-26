# Security

## Report a problem

Do not open a public Issue for a security problem. Use **Security > Report a vulnerability**
in this repository. A maintainer will answer within 7 days.

Examples of security problems:

- a way to make the bot merge a pull request that a second volunteer did not verify
- a way to make a workflow run code from a pull request
- a way for `hansard.py` to run commands or write files outside its folder
- a way to change the Hansard text so that `hansard.py check` does not detect it

## How the project protects itself

- The workflows that have write access (`pr-check`, `claim-bot`, `sweep`) run only code from the
  `main` branch. They read files from pull requests as data and never run them.
- A conversion pull request can change only files in `data/`.
- Each data file records the SHA-256 of its source PDF and of its own text.
- The bot merges a conversion only after a second volunteer converts the same PDFs and gets the same bytes.
- `main` cannot be force-pushed or deleted.
