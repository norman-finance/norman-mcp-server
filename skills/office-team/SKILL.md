---
name: office-team
description: Run an accounting office's team - who works there, what each person may open in the clients' books, who handles which client - and invite people, change access, assign clients or hand them over when someone leaves; also a client's own people and what they may open. Use when the office's owner or a manager asks to add an accountant, change someone's access, give clients to someone, when someone leaves the office, or about a client's employees.
version: 1.1.0
metadata:
  openclaw:
    emoji: "\U0001F465"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the office's owner or manager run the team:

## Step 1: Read the team
- Call `get_firm_team`: the people with their role (owner, manager, staff), whether they see every client, their `access` per part of the books, the clients they handle (the lead marked), the invitations not accepted yet, the clients nobody handles and the owners who have not joined
- `me.role` says what the caller may do: only an owner or a manager changes the team, only an owner invites or changes an owner. Staff read only
- The parts of the books: bookkeeping, invoices (with KSeF), documents (with messages), taxes_prepare, taxes_file, payroll, client_settings and, for a German office, datev. Each is `none`, `read` or `write`

## Step 2: Invite someone
- Ask for the e-mail, the role, the parts to close or make read-only, and for staff the clients they get
- Staff start with taxes_file, payroll and client_settings closed and see only their clients; owners and managers see every client
- Say who is invited with what, wait for a yes, then `invite_firm_member`. The e-mail goes out at once; `cancel_firm_invitation` withdraws it
- Someone working in another office on Norman or running a company of their own on Norman is refused: say so

## Step 3: Change access
- `update_firm_member` with only the parts that change. From then on a closed part answers that person with `advisor_block_closed`
- The office keeps at least one owner

## Step 4: Who handles which client
- Several clients to one person: `assign_clients_to_member` (as their lead by default), for example every client in `unassignedClients`
- One person's whole list: `set_member_clients` sets exactly those clients; read their current ones first and name what they lose
- One client's people and lead: `set_client_handlers`
- Name the clients and people and wait for a yes before each change

## Step 5: Someone leaves
- Count the clients they handle and lead, and ask who takes them over
- `remove_firm_member` with `hand_over_to` passes every client to that colleague, who leads the ones the person led. Without it the clients stay with whoever else handles them, or only with the people who see every client
- It cannot be undone here: the person would have to be invited again. Wait for a clear yes

## Step 6: A client's own people
- `list_client_people` with the client's `company_id`: its owner and members, what each may open, pending invitations, the seats of the client's plan and whether you may manage them (`canManage`: the owner, or the office when its firm opened the client's settings for you)
- `invite_client_person` (an employee, a co-founder) with the parts they may open; `update_client_person_access` sets a member's whole access (parts left out are open); `remove_client_person` and `cancel_client_person_invitation`
- The owner always sees everything and is never narrowed. A closed part answers the member with `member_block_closed`
- Name the client, the person and the access, and wait for a yes before each change
