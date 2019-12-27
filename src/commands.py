# This module defines logic for processing bot commands.
import base64
from accounting import Authorization
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS
from Crypto.Hash import SHA3_512


class CommandException(Exception):
    """The type of exception that is thrown when a command fails."""
    pass

def parse_transfer_command(message):
    """Parses a transfer command message."""
    body = message.split()
    if len(body) != 3:
        return None

    _, amount_text, destination = body
    try:
        amount = int(amount_text)
    except ValueError:
        return None

    return (amount, destination)

def process_transfer(author, message, server):
    """Processes a transfer command."""
    parse_result = parse_transfer_command(message)

    if parse_result is None:
        return 'Transfer formatted incorrectly. Expected `transfer AMOUNT BENEFICIARY`, ' \
            'where AMOUNT is a positive integer and BENEFICIARY is a username.'

    amount, destination_name = parse_result

    return perform_transfer(author, author, destination_name, amount, server)

def parse_admin_transfer_command(message):
    """Parses a transfer command message."""
    body = message.split()
    if len(body) != 4:
        return None

    _, amount_text, sender, destination = body
    try:
        amount = int(amount_text)
    except ValueError:
        return None

    return (sender, amount, destination)

def process_admin_transfer(author, message, server):
    """Processes an admin transfer command."""
    assert_authorized(author, server, Authorization.ADMIN)
    parse_result = parse_admin_transfer_command(message)

    if parse_result is None:
        return 'Admin transfer formatted incorrectly. Expected `admin-transfer AMOUNT SENDER BENEFICIARY`, ' \
            'where AMOUNT is a positive integer and SENDER, BENEFICIARY are account holders.'

    sender_name, amount, destination_name = parse_result

    return perform_transfer(author, sender_name, destination_name, amount, server)

def perform_transfer(author_name, sender_name, destination_name, amount, server):
    """Helper function that performs a transfer."""
    author = assert_is_account(author_name, server)
    sender = assert_is_account(sender_name, server)
    dest = assert_is_account(destination_name, server)

    # TODO: check for common reasons for why a transfer might not be able to go through (e.g., insufficient
    # balance) and provide a helpful error message for each of those cases.

    if not server.can_transfer(sender, dest, amount):
        return 'Sorry, but I can\'t perform that transfer.'

    proof = server.transfer(author, sender, dest, amount)
    proof_string = ' Proof: %s.' % proof if proof is not None else ''
    return 'Transfer performed successfully.%s' % proof_string

def process_open_account(author, message, server):
    """Processes a message that tries to open a new account."""
    if server.has_account(author):
        return 'Hi there %s. Looks like you already have an account. No need to open another one.' % author

    server.open_account(author)
    return 'Hi there %s. Your account has been opened successfully. Thank you for your business.' % author

def process_admin_open_account(author, message, server):
    """Processes a message that tries to open a new account."""
    assert_authorized(author, server, Authorization.ADMIN)
    body = message.split()
    if len(body) != 2:
        raise CommandException(
            'Incorrectly formatted command; expected `admin-open ACCOUNT_NAME`, '
            'where `ACCOUNT_NAME` is the name of the account to create.')

    account_name = body[1]
    if server.has_account(account_name):
        raise CommandException('Account `%s` already exists.' % account_name)

    server.open_account(account_name)
    return 'Account `%s` has been opened successfully.' % account_name

def process_balance(author, message, server):
    """Processes a message requesting the balance on an account."""
    if not server.has_account(author):
        return 'Hi there %s. I can\'t tell you what the balance on your account is because you don\'t have an account yet. ' \
            'You can open one with the `open` command.' % author

    account = server.get_account(author)
    main_response = 'The balance on your account is %s.' % account.get_balance()
    return 'Hi there %s %s. %s Have a great day.' % (account.get_authorization().name.lower(), author, main_response)

def process_add_public_key(author, message, server):
    """Processes a message that requests for a public key to be associated with an account."""
    account = assert_is_account(author, server)
    pem = '\n'.join(line for line in message.split('\n')[1:] if line != '' and not line.isspace())
    try:
        print(repr(pem))
        key = ECC.import_key(pem)
    except Exception as e:
        raise CommandException("Incorrectly formatted key. Inner error message: %s." % str(e))

    server.add_public_key(account, key)
    return 'Public key added successfully.'

def assert_is_account(account_name, server):
    """Asserts that a particular account exists. Returns the account."""
    if not server.has_account(account_name):
        raise CommandException('Sorry, I can\'t process your request because `%s` does not have an account yet.' % account_name)

    return server.get_account(account_name)

def assert_authorized(account_name, server, auth_level):
    """Asserts that a particular account exists and has an authorization level that is at least `auth_level`.
       Returns the account."""
    account = assert_is_account(account_name, server)

    if account.get_authorization().value < auth_level.value:
        raise CommandException('Sorry, I can\'t process your request because `%s` does not have the required authorization.' % account_name)

    return account

def parse_authorization(message):
    """Parses an authorization message."""
    body = message.split()
    if len(body) != 3:
        return None

    _, beneficiary, auth_level = body
    auth_level = auth_level.upper()
    try:
        return (beneficiary, Authorization[auth_level])
    except KeyError:
        return None

def process_authorization(author, message, server):
    """Processes a message requesting an authorization change."""
    author_account = assert_authorized(author, server, Authorization.ADMIN)
    parsed = parse_authorization(message)
    if parsed is None:
        raise CommandException('Authorization formatted incorrectly. The right format is `authorize BENEFICIARY citizen|admin|developer`.')

    beneficiary, auth_level = parsed
    beneficiary_account = assert_is_account(beneficiary, server)
    server.authorize(author_account, beneficiary_account, auth_level)
    return '%s now has authorization level %s.' % (beneficiary, auth_level.name)

def process_list_accounts(author, message, server):
    """Processes a message requesting a list of all accounts."""
    return '\n'.join(['| Account | Balance |', '| --- | --- |'] + [
        '| %s | %s |' % (str(server.get_account_id(account)), account.get_balance())
        for account in server.list_accounts()
    ])

def parse_print_money(message):
    """Parses a money printing request."""
    body = message.split()
    if len(body) != 3:
        return None

    _, amount_text, beneficiary = body
    try:
        amount = int(amount_text)
    except ValueError:
        return None
    
    return (amount, beneficiary)

def process_print_money(author, message, server):
    """Processes a request to print a batch of money and deposit it in an account."""
    author_account = assert_authorized(author, server, Authorization.ADMIN)
    parsed = parse_print_money(message)
    if parsed is None:
        raise CommandException('Command formatted incorrectly. Expected format `print-money AMOUNT BENEFICIARY`.')

    amount, beneficiary = parsed
    beneficiary_account = assert_is_account(beneficiary, server)
    server.print_money(author_account, beneficiary_account, amount)
    return 'Money printed successfully.'

def parse_admin_create_recurring_transfer(message):
    """Parses an admin-create-recurring-transfer message."""
    body = message.split()
    if len(body) != 5:
        return None

    _, amount_text, sender, destination, tick_count_text = body
    try:
        amount = int(amount_text)
        tick_count = int(tick_count_text)
    except ValueError:
        return None

    return (amount, sender, destination, tick_count)

def process_admin_create_recurring_transfer(author, message, server):
    """Processes a request to set up an arbitrary recurring transfer."""
    assert_authorized(author, server, Authorization.ADMIN)
    parse_result = parse_admin_create_recurring_transfer(message)

    if parse_result is None:
        return 'Request formatted incorrectly. Expected `admin-create-recurring-transfer AMOUNT_PER_TICK SENDER BENEFICIARY TICK_COUNT`.'

    amount, sender_name, destination_name, tick_count = parse_result

    author_account = assert_is_account(author, server)
    sender_account = assert_is_account(sender_name, server)
    dest_account = assert_is_account(destination_name, server)

    transfer = server.create_recurring_transfer(
        author_account,
        sender_account,
        dest_account,
        amount * tick_count,
        tick_count)
    return 'Recurring transfer set up with ID `%s`.' % transfer.get_id()

def parse_proxy_command(message):
    """Parses a proxy command into its components."""
    def parse_impl():
        split_message = message.split('\n', 1)
        if len(split_message) != 2:
            return None

        proxy_line, command = split_message
        command = command.strip('\n\r')

        proxy_elems = proxy_line.split()
        if len(proxy_elems) != 4:
            return None

        _, protocol, account_name, enc_signature = proxy_elems
        if protocol != 'dsa':
            return None

        try:
            signature = base64.b64decode(enc_signature)
        except Exception as e:
            raise CommandException("Invalid signature. %s" % str(e))

        return (account_name, signature, command)

    result = parse_impl()
    if result == None:
        raise CommandException('Invalid formatting; expected `proxy dsa PROXIED_ACCOUNT SIGNATURE` followed by another command on the next line.')
    else:
        return result

def compose_proxy_command(proxied_account_name, key, command):
    """Composes a proxy command."""
    command = command.strip()
    command_hash = SHA3_512.new(command.encode('utf-8'))
    signer = DSS.new(key, 'fips-186-3')
    signature = base64.b64encode(signer.sign(command_hash)).decode('utf-8')
    return 'proxy dsa %s %s\n%s' % (proxied_account_name, signature, command)

def process_proxy_command(author, message, server):
    """Processes a command by proxy."""
    account_name, signature, command = parse_proxy_command(message)
    account = assert_is_account(account_name, server)
    command_hash = SHA3_512.new(command.encode('utf-8'))
    any_verified = False
    for key in account.list_public_keys():
        verifier = DSS.new(key, 'fips-186-3')
        try:
            verifier.verify(command_hash, signature)
            any_verified = True
        except ValueError:
            pass

        if any_verified:
            break

    if any_verified:
        return process_command(account_name, command, server)
    else:
        raise CommandException('Cannot execute command by proxy because the signature is invalid.')

def process_command(author, message, server):
    """Processes an arbitrary command."""
    split_msg = message.split()
    if len(split_msg) == 0:
        return 'Hi %s! You sent me an empty message. Here\'s a list of commands I do understand:\n\n%s' % (
            author, list_commands_as_markdown(author, server))
    elif split_msg[0] in COMMANDS:
        try:
            cmd = COMMANDS[split_msg[0]]
            if len(cmd) >= 4 and cmd[3].value > Authorization.CITIZEN.value:
                assert_authorized(author, server, cmd[3])

            return cmd[2](author, message, server)
        except CommandException as e:
            return str(e)
    else:
        return 'Hi %s! I didn\'t quite understand command your command `%s`. Here\'s a list of commands I do understand:\n\n%s' % (
            author, split_msg[0], list_commands_as_markdown(author, server))

def list_commands(author, server):
    """Creates a list of all commands accepted by this bot."""
    return [
        '`%s` &ndash; %s' % (COMMANDS[key][0], COMMANDS[key][1])
        for key in sorted(COMMANDS)
        if len(COMMANDS[key]) < 4 or get_authorization_or_citizen(author, server).value >= COMMANDS[key][3].value
    ]

def get_authorization_or_citizen(author, server):
    """Gets an account's authorization if it exists and the default citizen authorization otherwise."""
    return server.get_account(author).get_authorization() \
        if server.has_account(author) \
        else Authorization.CITIZEN

def list_commands_as_markdown(author, server):
    """Creates a list of all commands accepted by this bot and formats it as Markdown."""
    return '\n'.join('  * %s' % item for item in list_commands(author, server))

def process_help(author, message, server):
    """Gets the help message for the economy bot."""
    return '''
Hi %s! Here's a list of the commands I understand:

%s''' % (author, list_commands_as_markdown(author, server))

# A list of the commands accepted by the bot. Every command
# is essentially a function that maps a message to a reply.
# For convenience, every command is associated with a help
# string here.
COMMANDS = {
    'help': ('help', 'prints a help message.', process_help),
    'transfer': ('transfer AMOUNT BENEFICIARY', 'transfers AMOUNT to user BENEFICIARY\'s account.', process_transfer),
    'open': ('open', 'opens a new account.', process_open_account),
    'balance': ('balance', 'prints the balance on your account.', process_balance),
    'add-public-key': (
        'add-public-key',
        'associates an ECC public key with your account. '
        'The public key should be encoded as the contents of a PEM file that is placed on a line after the command itself.',
        process_add_public_key),
    'proxy': (
        'proxy dsa PROXIED_ACCOUNT SIGNATURE',
        'makes PROXIED_ACCOUNT describes the action described in the remainder of the message (starting on the next line). '
        'SIGNATURE must be an ECDSA-signed SHA3-512 hash of the remainder of the message, where the key that signs the '
        'message must have its public key associated with the proxied account. This command allows a user or application to '
        'safely perform actions on an account holder\'s behalf.',
        process_proxy_command),
    'authorize': (
        'authorize ACCOUNT citizen|admin|developer',
        'sets an account\'s authorization.',
        process_authorization,
        Authorization.ADMIN),
    'admin-transfer': (
        'admin-transfer AMOUNT SENDER BENEFICIARY',
        'transfers AMOUNT from SENDER to BENEFICIARY.',
        process_admin_transfer,
        Authorization.ADMIN),
    'list': (
        'list',
        'lists all accounts and the balance on the accounts.',
        process_list_accounts,
        Authorization.ADMIN),
    'print-money': (
        'print-money AMOUNT BENEFICIARY',
        'generates AMOUNT money and deposits it in BENEFICIARY\'s account.',
        process_print_money,
        Authorization.ADMIN),
    'admin-create-recurring-transfer': (
        'admin-create-recurring-transfer AMOUNT_PER_TICK SENDER BENEFICIARY TICK_COUNT',
        'creates a transfer that will transfer AMOUNT_PER_TICK from SENDER to BENEFICIARY every tick, for TICK_COUNT ticks.',
        process_admin_create_recurring_transfer,
        Authorization.ADMIN),
    'admin-open': (
        'admin-open ACCOUNT_NAME',
        'opens a new account with a particular name. '
            'If a user has ACCOUNT_NAME, then the newly created account will become that user\'s account.',
        process_admin_open_account,
        Authorization.ADMIN)
}
