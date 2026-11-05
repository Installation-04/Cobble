# Simple chat bot

A small rule-based chat bot for a website. It greets people, answers the keywords its owner configures, does simple calculations, and keeps the history of the conversations. No language model inside: the answers come from fixed rules. No accounts and no login.

## Features
- **Send a message**: `user` (1 to 30 characters) and `text` (1 to 500 characters). The answer is `{"reply": "..."}`. Every message and its reply are kept in the history.
- A text that starts with `/` is a **command** (the command name is not case sensitive, the rest of the text is taken as it is). Rules and greetings never apply to commands.
  - `/help` replies `Commands: /help, /echo, /calc, /count`.
  - `/echo <text>` replies exactly `<text>`, everything after the first space. Without text it replies `Usage: /echo <text>`.
  - `/calc <expression>` computes an expression with decimal numbers, `+`, `-`, `*`, `/`, parentheses and a minus sign in front of a number or a parenthesis, with the usual priorities. The reply is the result: an integer without decimals (`14`), otherwise at most 6 decimals without trailing zeros (`2.5`, `0.333333`). A division by zero replies `Error: division by zero`. Anything else that cannot be read replies `Error: invalid expression`. The expression must never be run as code.
  - `/count` replies how many messages this user has sent, **this one included**: `You have sent 1 message.` or `You have sent 3 messages.`
  - Any other command replies `Unknown command: /name. Try /help.` (with the command as typed, in lowercase).
- Otherwise the bot looks at the **keyword rules**, in the order they were created. A rule matches when its keyword appears in the text as a whole word, ignoring case (`price` matches `What is the PRICE?` but not `pricey`). The first matching rule gives its reply.
- If no rule matches and the text contains one of the whole words `hello`, `hi`, `bonjour`, `salut` (ignoring case), the reply is `Hello <user>!`.
- Otherwise the reply is `Sorry, I did not understand. Try /help.`
- **Rules**: create one with a `keyword` (1 to 30 characters) and a `reply` (1 to 200 characters); two rules cannot have the same keyword (ignoring case, 409). List them in creation order. Delete one.
- **History**: the messages with their replies, oldest first, optionally for one `user`, limited to the latest `limit` messages (default 50, from 1 to 200), still oldest first.

## Screens
- A chat page: the conversation, a text box, and a small admin area to add and remove keyword rules.

## Data model
- Message: user, text, reply, timestamp (UTC, `YYYY-MM-DDTHH:MM:SSZ`).
- Rule: id, keyword, reply.

## Constraints
- FastAPI backend, data kept on disk (it survives a restart).
- Usable on a phone screen.

## Out of scope
- Language models, accounts, several channels, scheduled messages.

## Acceptance criteria
- `GET /api/health` answers 200.
- `POST /api/messages` answers 200 with the reply (422 for invalid fields).
- `POST /api/rules` (201, 409 for a duplicate keyword, 422 for invalid fields), `GET /api/rules`, `DELETE /api/rules/{id}` (204, 404 if unknown).
- `GET /api/history?user=&limit=`.
