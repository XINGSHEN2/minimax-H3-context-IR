"""Apply reviewed JSON field patches without regenerating unaffected content."""
import copy, re

def apply_patches(document, patches):
    result = copy.deepcopy(document)
    for patch in patches:
        op = patch['op']
        path = patch['path']
        if op not in {'replace', 'add', 'remove'} or not isinstance(path, str) or (not path.startswith('/')) or (path == '/'):
            raise ValueError('Invalid patch operation/path')
        parts = path[1:].split('/')
        if any((re.search('~(?![01])', p) for p in parts)):
            raise ValueError('Invalid pointer escape')
        parts = [p.replace('~1', '/').replace('~0', '~') for p in parts]
        node = result
        for part in parts[:-1]:
            if isinstance(node, list):
                if not part.isdigit() or str(int(part)) != part:
                    raise ValueError('Invalid list index')
                node = node[int(part)]
            else:
                node = node[part]
        key = parts[-1]
        if isinstance(node, list):
            if key == '-' and op == 'add':
                node.append(copy.deepcopy(patch['value']))
                continue
            if not key.isdigit() or str(int(key)) != key:
                raise ValueError('Invalid list index')
            idx = int(key)
            if idx >= len(node) and (not (op == 'add' and idx == len(node))):
                raise ValueError('Index out of range')
            if op == 'remove':
                node.pop(idx)
            elif op == 'replace':
                node[idx] = copy.deepcopy(patch['value'])
            else:
                node.insert(idx, copy.deepcopy(patch['value']))
        elif isinstance(node, dict):
            if op in {'replace', 'remove'} and key not in node:
                raise ValueError('Path does not exist')
            if op == 'remove':
                del node[key]
            else:
                node[key] = copy.deepcopy(patch['value'])
        else:
            raise ValueError('Pointer does not address a container')
    return result

def addressable(document):
    """Address top-level entity collections by stable IDs, never array offsets."""
    result = copy.deepcopy(document)
    collections = []
    for name in ('shots', 'events', 'text_blocks'):
        if name not in result:
            continue
        items = result[name]
        if not isinstance(items, list):
            raise ValueError('Entity collection must be a list')
        mapped = {}
        for item in items:
            if not isinstance(item, dict) or item.get('id') is None:
                raise ValueError('Entity requires id')
            key = str(item['id'])
            if not key or key in mapped:
                raise ValueError('Duplicate or empty entity id')
            mapped[key] = item
        result[name] = mapped
        collections.append(name)
    return (result, collections)

def restore_collections(document, collections):
    result = copy.deepcopy(document)
    for name in collections:
        mapped = result.get(name)
        if not isinstance(mapped, dict):
            raise ValueError('Entity collection must remain keyed')
        for (key, item) in mapped.items():
            if not isinstance(item, dict) or str(item.get('id')) != key:
                raise ValueError('Entity id must match its address')
        result[name] = list(mapped.values())
    return result
