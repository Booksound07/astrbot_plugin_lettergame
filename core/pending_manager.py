pending_query = {}

pending_add_alias = {}

def set_pending_query(key, data):
    pending_query[key] = data


def get_pending_query(key):
    return pending_query.get(key)


def remove_pending_query(key):
    pending_query.pop(key, None)
    
def set_pending_alias(key, data):
    pending_add_alias[key] = data


def get_pending_alias(key):
    return pending_add_alias.get(key)


def remove_pending_alias(key):
    pending_add_alias.pop(key, None)