"""Address-independent identity of one captured completion UI subtree."""


def completion_signature(nodes, root):
    indices={}
    signature=[]
    for node in nodes:
        if node['address']!=root and node['parent'] not in indices:
            continue
        name=node.get('name') or ''
        if name.lower()==node['address'].lower().removeprefix('0x'):
            name=''
        signature.append([indices.get(node['parent'],-1),node['vtable'],name,node.get('text') or ''])
        indices[node['address']]=len(signature)-1
    if not signature:
        raise ValueError('Completion root missing')
    return signature
