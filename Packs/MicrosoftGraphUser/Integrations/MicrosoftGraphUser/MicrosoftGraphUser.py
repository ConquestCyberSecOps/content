import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *
from typing import Dict

# disable insecure warnings
requests.packages.urllib3.disable_warnings()

''' CONSTANTS '''
BLOCK_ACCOUNT_JSON = '{"accountEnabled": false}'
UNBLOCK_ACCOUNT_JSON = '{"accountEnabled": true}'
NO_OUTPUTS: dict = {}
APP_NAME = 'ms-graph-user'


def camel_case_to_readable(text):
    """
    'camelCase' -> 'Camel Case'
    """
    if text == 'id':
        return 'ID'
    return ''.join(' ' + char if char.isupper() else char.strip() for char in text).strip().title()


def parse_outputs(users_data):
    """
    Parse user data as received from Microsoft Graph API into Demisto's conventions
    """
    if isinstance(users_data, list):
        users_readable, users_outputs = [], []
        for user_data in users_data:
            user_readable = {camel_case_to_readable(k): v for k, v in user_data.items() if k != '@removed'}
            if '@removed' in user_data:
                user_readable['Status'] = 'deleted'
            users_readable.append(user_readable)
            users_outputs.append({k.replace(' ', ''): v for k, v in user_readable.copy().items()})

        return users_readable, users_outputs

    else:
        user_readable = {camel_case_to_readable(k): v for k, v in users_data.items() if k != '@removed'}
        if '@removed' in users_data:
            user_readable['Status'] = 'deleted'
        user_outputs = {k.replace(' ', ''): v for k, v in user_readable.copy().items()}

        return user_readable, user_outputs


class MsGraphClient:
    """
    Microsoft Graph Mail Client enables authorized access to a user's Office 365 mail data in a personal account.
    """

    def __init__(self, tenant_id, auth_id, enc_key, app_name, base_url, verify, proxy, self_deployed):
        self.ms_client = MicrosoftClient(tenant_id=tenant_id, auth_id=auth_id, enc_key=enc_key, app_name=app_name,
                                         base_url=base_url, verify=verify, proxy=proxy, self_deployed=self_deployed)

    def terminate_user_session(self, user):
        self.ms_client.http_request(
            method='PATCH',
            url_suffix=f'users/{user}',
            data=BLOCK_ACCOUNT_JSON)

    def unblock_user(self, user):
        self.ms_client.http_request(
            method='PATCH',
            url_suffix=f'users/{user}',
            data=UNBLOCK_ACCOUNT_JSON)

    def delete_user(self, user):
        self.ms_client.http_request(
            method='DELETE',
            url_suffix=f'users/{user}')

    def create_user(self, properties):
        self.ms_client.http_request(
            method='POST',
            url_suffix='users',
            json_data=properties)

    def update_user(self, user, updated_fields):
        body = {}
        for key_value in updated_fields.split(','):
            field, value = key_value.split('=', 2)
            body[field] = value
        self.ms_client.http_request(
            method='PATCH',
            url_suffix=f'users/{user}',
            json_data=body)

    def get_delta(self, properties):
        users = self.ms_client.http_request(
            method='GET',
            url_suffix='users/delta',
            params={'$select': properties})
        return users.get('value', '')

    def get_user(self, user, properties):
        user_data = self.ms_client.http_request(
            method='GET ',
            url_suffix=f'users/{user}',
            params={'$select': properties})
        return user_data.pop('@odata.context', None)

    def list_users(self, properties, page_url):
        if page_url:
            response = self.ms_client.http_request(method='GET', full_url=page_url)
        else:
            response = self.ms_client.http_request(method='GET', url_suffix='users', params={'$select': properties})
        next_page_url = response.get('@odata.nextLink')
        users = response.get('value')
        return users, next_page_url


def test_function(client, _):
    """
       Performs basic GET request to check if the API is reachable and authentication is successful.
       Returns ok if successful.
       """
    client.ms_client.http_request(method='GET', url_suffix='users/')
    return 'ok', None, None


def terminate_user_session_command(client: MsGraphClient, args: Dict):
    user = args.get('user')
    client.terminate_user_session(user)
    human_readable = f'user: "{user}" session has been terminated successfully'
    return human_readable, None, None


def unblock_user_command(client: MsGraphClient, args: Dict):
    user = args.get('user')
    client.unblock_user(user)
    human_readable = f'"{user}" unblocked. It might take several minutes for the changes to take affect across all ' \
                     f'applications. '
    return human_readable, None, None


def delete_user_command(client: MsGraphClient, args: Dict):
    user = args.get('user')
    client.delete_user(user)
    human_readable = f'user: "{user}" was deleted successfully'
    return human_readable, None, None


def create_user_command(client: MsGraphClient, args: Dict):
    required_properties = {
        'accountEnabled': args.get('account_enabled'),
        'displayName': args.get('display_name'),
        'onPremisesImmutableId': args.get('on_premises_immutable_id'),
        'mailNickname': args.get('mail_nickname'),
        'passwordProfile': {
            "forceChangePasswordNextSignIn": 'true',
            "password": args.get('password')
        },
        'userPrincipalName': args.get('user_principal_name')
    }
    other_properties = {}
    if args.get('other_properties'):
        for key_value in args.get('other_properties', '').split(','):
            key, value = key_value.split('=', 2)
            other_properties[key] = value
        required_properties.update(other_properties)

    # create the user
    client.create_user(required_properties)

    # display the new user and it's properties
    user = required_properties.get('userPrincipalName')
    user_data = client.get_user(user, '*')
    user_readable, user_outputs = parse_outputs(user_data)
    human_readable = tableToMarkdown(name=f"{user} was created successfully:", t=user_readable, removeNull=True)
    outputs = {'MSGraphUser(val.ID == obj.ID)': user_outputs}
    return human_readable, outputs, user_data


def update_user_command(client: MsGraphClient, args: Dict):
    user = args.get('user')
    updated_fields = args.get('updated_fields')

    client.update_user(user, updated_fields)
    get_user_command(client, args)


def get_delta_command(client: MsGraphClient, args: Dict):
    properties = args.get('properties', '') + ',userPrincipalName'
    users_data = client.get_delta(properties)
    headers = list(set([camel_case_to_readable(p) for p in argToList(properties)] + ['ID', 'User Principal Name']))

    users_readable, users_outputs = parse_outputs(users_data)
    human_readable = tableToMarkdown(name='All Graph Users', headers=headers, t=users_readable, removeNull=True)
    outputs = {'MSGraphUser(val.ID == obj.ID)': users_outputs}
    return human_readable, outputs, users_data


def get_user_command(client: MsGraphClient, args: Dict):
    user = args.get('user')
    properties = args.get('properties', '*')
    user_data = client.get_user(user, properties)

    user_readable, user_outputs = parse_outputs(user_data)
    human_readable = tableToMarkdown(name=f"{user} data", t=user_readable, removeNull=True)
    outputs = {'MSGraphUser(val.ID == obj.ID)': user_outputs}
    return human_readable, outputs, user_data


def list_users_command(client: MsGraphClient, args: Dict):
    properties = args.get('properties', 'id,displayName,jobTitle,mobilePhone,mail')
    next_page = args.get('next_page', None)
    users_data, result_next_page = client.list_users(properties, next_page)
    users_readable, users_outputs = parse_outputs(users_data)
    metadata = None
    outputs = {'MSGraphUser(val.ID == obj.ID)': users_outputs}

    if result_next_page:
        metadata = "To get further results, enter this to the next_page parameter:\n" + str(result_next_page)

        # .NextPage.indexOf(\'http\')>=0 : will make sure the NextPage token will always be updated because it's a url
        outputs['MSGraphUser(val.NextPage.indexOf(\'http\')>=0)'] = {'NextPage': result_next_page}

    human_readable = tableToMarkdown(name='All Graph Users', t=users_readable, removeNull=True, metadata=metadata)

    return human_readable, outputs, users_data


def main():
    params: dict = demisto.params()
    url = params.get('url', '').rstrip('/') + '/v1.0/'
    tenant = params.get('tenant_id')
    auth_and_token_url = params.get('auth_id', '')
    enc_key = params.get('enc_key')
    verify = not params.get('insecure', False)
    self_deployed: bool = params.get('self_deployed', False)
    # TODO: check it does the same as handle proxy
    proxy = params.get('proxy', False)

    commands = {
        'test-module': test_function,
        'msgraph-user-unblock': unblock_user_command,
        'msgraph-user-terminate-session': terminate_user_session_command,
        'msgraph-user-update': update_user_command,
        'msgraph-user-delete': delete_user_command,
        'msgraph-user-create': create_user_command,
        'msgraph-user-get-delta': get_delta_command,
        'msgraph-user-get': get_user_command,
        'msgraph-user-list': list_users_command
    }
    command = demisto.command()
    LOG(f'Command being called is {command}')

    try:
        # TODO: Check handle_proxy() function and see if it exists in MsApiModule
        client: MsGraphClient = MsGraphClient(tenant_id=tenant, auth_id=auth_and_token_url, enc_key=enc_key,
                                              app_name=APP_NAME, base_url=url, verify=verify, proxy=proxy,
                                              self_deployed=self_deployed)

        human_readable, entry_context, raw_response = commands[command](client, demisto.args())  # type: ignore
        return_outputs(readable_output=human_readable, outputs=entry_context, raw_response=raw_response)

    except Exception as err:
        return_error(str(err))


from MicrosoftApiModule import *  # noqa: E402

if __name__ in ['__main__', 'builtin', 'builtins']:
    main()
