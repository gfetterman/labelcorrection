import copy
import itertools
import numbers
import tempfile
import codecs
import yaml
import uuid
import hashlib
import collections
import functools as ft

__version__ = "0.2"

class CorrectionStack:
    def __init__(self, labels, ops_file, load, apply=False):
        """Creates a CorrectionStack.
        
           labels -- a list of dicts denoted event data
           ops_file -- filename string to save operations
           load -- bool; if True, load from ops_file
           apply -- bool; if True and if load, apply corrections in ops_file"""
        self.labels = labels
        self.file = ops_file
        if load:
            self.read_from_file(apply=apply)
        else:
            self.undo_stack = collections.deque()
            self.redo_stack = collections.deque()
            self.uuid = str(uuid.uuid4())
            self.label_hash = self._make_label_hash()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, exc_trace):
        if exc_type is None:
            self.write_to_file()
            return True
        else:
            self.write_to_file(self.file + '.bak')
            return False
    
    def _make_label_hash(self):
        """Returns SHA-1 hash of labels the stack's operations act on."""
        return hashlib.sha1(repr(self.labels).encode()).hexdigest()
    
    def read_from_file(self, file=None, apply=False):
        """Read a stack of corrections plus metadata from file.
           
           file -- if not present, use self.file
           apply -- bool; if True, apply loaded corrections
                          if False, assume corrections already applied"""
        if file:
            self.file = file
        with codecs.open(self.file, 'r', encoding='utf-8') as fp:
            self.undo_stack = collections.deque()
            self.redo_stack = collections.deque()
            for op in fp:
                if op != '\n':
                    if apply:
                        self._apply(parse(op.strip()))
                    self.undo_stack.append(parse(op.strip()))
        with codecs.open((self.file + '.yaml'), 'r', encoding='utf-8') as mdfp:
            file_data = yaml.safe_load(mdfp)
            self.uuid = file_data['uuid']
            self.label_hash = file_data['label_hash']
    
    def write_to_file(self, file=None):
        """Write stack of corrections plus metadata to file.
           
           file -- if not present, use self.file"""
        if file:
            self.file = file
        with codecs.open(self.file, 'w', encoding='utf-8') as fp:
            for op in self.undo_stack:
                fp.write(deparse(op) + '\n')
        with codecs.open((self.file + '.yaml'), 'w', encoding='utf-8') as mdfp:
            file_data = {'uuid': self.uuid, 'label_hash': self.label_hash}
            mdfp.write("""# corrections metadata, YAML syntax\n---\n""")
            mdfp.write(yaml.safe_dump(file_data, default_flow_style=False))
    
    def undo(self):
        """Undoes last executed command, if any.
           Raises an IndexError if the undo_stack is empty."""
        inv = invert(self.undo_stack.pop())
        self.redo_stack.append(inv)
        self._apply(inv)
    
    def redo(self):
        """Redoes last undone command, if any.
           Raises an IndexError if the redo_stack is empty."""
        inv = invert(self.redo_stack.pop())
        self.undo_stack.append(inv)
        self._apply(inv)
    
    def push(self, cmd):
        """Executes command, discarding redo stack."""
        self.redo_stack.clear()
        self.undo_stack.append(cmd)
        self._apply(cmd)
    
    def peek(self, index=-1):
        """Returns command string at top of undo stack, or index."""
        return self.undo_stack[index]
    
    def _apply(self, s_expr):
        """Executes s-expression, applied to labels."""
        evaluate(s_expr, make_env(labels=self.labels))
    
    # operations
    
    def rename(self, index, new_name):
        """Renames an event."""
        self.push(self.codegen_rename(index, new_name))
    
    def set_start(self, index, new_start):
        """Changes the start time of an event."""
        self.push(self.codegen_set_start(index, new_start))
    
    def set_stop(self, index, new_stop):
        """Changes the stop time of an event."""
        self.push(self.codegen_set_stop(index, new_stop))
    
    def merge_next(self, index, new_name=None):
        """Merges an event with its successor."""
        self.push(self.codegen_merge_next(index, new_name))
    
    def split(self, index, new_sep, new_name=None, new_next_name=None):
        """Splits an event in two."""
        self.push(self.codegen_split(index, new_sep, new_name, new_next_name))
    
    def delete(self, index):
        """Deletes an event."""
        self.push(self.codegen_delete(index))
    
    def create(self, index, start, **kwargs):
        """Creates a new event."""
        self.push(self.codegen_create(index, start, **kwargs))
    
    # code generators
    
    def _gen_code(self, op, target_name, target, other_args):
        """Generates an s-expression for the given op.
           
           op -- string
           target_name -- string
           target -- dict
           other_args -- dict"""
        ntl = [Symbol(op)]
        ntl.append(KeyArg('labels'))
        ntl.append(Symbol('labels'))
        ntl.append(KeyArg('target'))
        ntl.append([Symbol(target_name)])
        for k, a in target.items():
            ntl[-1].append(KeyArg(k))
            ntl[-1].append(a)
        for k, a in other_args.items():
            ntl.append(KeyArg(k))
            ntl.append(a)
        return ntl

    def codegen_rename(self, index, new_name):
        """Generates command string to rename an interval.
           
           new_name -- string"""
        op = 'set_name'
        target_name = 'interval'
        target = {'index': index,
                  'name': self.labels[index]['name']}
        other_args = {'new_name': new_name}
        return self._gen_code(op, target_name, target, other_args)

    def codegen_set_start(self, index, new_start):
        """Generates command string to move an interval's start.
           
           new_start -- float"""
        op = 'set_start'
        target_name = 'interval'
        target = {'index': index,
                  'start': self.labels[index]['start']}
        other_args = {'new_start': new_start}
        return self._gen_code(op, target_name, target, other_args)

    def codegen_set_stop(self, index, new_stop):
        """Generates command string to move an interval's stop.
           
           new_stop -- float"""
        op = 'set_stop'
        target_name = 'interval'
        target = {'index': index,
                  'stop': self.labels[index]['stop']}
        other_args = {'new_stop': new_stop}
        return self._gen_code(op, target_name, target, other_args)

    def codegen_merge_next(self, index, new_name=None):
        """Generates command string to merge an interval and its successor.
           
           new_name -- string; if absent, new interval name is concatenation
                       of two parents' names"""
        op = 'merge_next'
        target_name = 'interval_pair'
        target = {'index': index,
                  'name': self.labels[index]['name'],
                  'stop': self.labels[index]['stop'],
                  'next_start': self.labels[index + 1]['start'],
                  'next_name': self.labels[index + 1]['name']}
        if new_name is None:
            new_name = target['name'] + target['next_name']
        other_args = {'new_name': new_name,
                      'new_stop': None,
                      'new_next_start': None,
                      'new_next_name': None}
        columns = [c for c in self.labels[index].keys()
                   if c not in ('start', 'stop', 'name')]
        for c in columns:
            target[c] = self.labels[index][c]
            target['next_' + c] = self.labels[index + 1][c]
            other_args['new_' + c] = None
            other_args['new_next_' + c] = None
        return self._gen_code(op, target_name, target, other_args)

    def codegen_split(self, index, new_sep, new_name=None,
                      new_next_name=None, **kwargs):
        """Generates command string to split an interval in two.
           
           new_sep -- number; must be within interval's limits
           new_name -- string; if absent"""
        op = 'split'
        target_name = 'interval_pair'
        target = {'index': index,
                  'name': self.labels[index]['name'],
                  'stop': self.labels[index]['stop'],
                  'next_name': None,
                  'next_start': None,}
        if new_name is None:
            new_name = target['name']
        if new_next_name is None:
            new_next_name = ''
        other_args = {'new_name': new_name,
                      'new_stop': new_sep,
                      'new_next_start': new_sep,
                      'new_next_name': new_next_name}
        columns = [c for c in self.labels[index].keys()
                   if c not in ('start', 'stop', 'name')]
        for c in columns:
            target[c] = self.labels[index][c]
            target['next_' + c] = None
            other_args['new_' + c] = kwargs['new_' + c]
            other_args['new_next_' + c] = kwargs['new_next_' + c]
        return self._gen_code(op, target_name, target, other_args)

    def codegen_delete(self, index):
        """Generates command string to delete an interval."""
        op = 'delete'
        target_name = 'interval'
        target = {'index': index}
        target.update(self.labels[index])
        other_args = {}
        return self._gen_code(op, target_name, target, other_args)

    def codegen_create(self, index, start, **kwargs):
        """Generates command string to create a new interval.
           
           start -- float
           kwargs -- any other column values the interval possesses"""
        op = 'create'
        target_name = 'interval'
        target = {'index': index,
                  'start': start}
        target.update(kwargs)
        other_args = {}
        return self._gen_code(op, target_name, target, other_args)


# raw operations

def _set_value(labels, target, column, **kwargs):
    labels[target['index']][column] # raise KeyError if column not present
    labels[target['index']][column] = kwargs['new_' + column]

def _merge_next(labels, target, **kwargs):
    index = target['index']
    labels[index]['stop'] = labels[index + 1]['stop']
    labels[index]['name'] = kwargs['new_name']
    labels.pop(index + 1)

def _split(labels, target, **kwargs):
    if not (kwargs['new_stop'] > labels[target['index']]['start'] and
            kwargs['new_next_start'] < labels[target['index']]['stop']):
        raise ValueError('split point must be within interval')
    index = target['index']
    new_point = copy.deepcopy(labels[index])
    for key in kwargs:
        if key[:9] == 'new_next_':
            new_point[key[9:]] = kwargs[key]
        elif key[:4] == 'new_':
            labels[index][key[4:]] = kwargs[key]
    labels.insert(index + 1, new_point)

def _delete(labels, target, **kwargs):
    labels.pop(target['index'])

def _create(labels, target, **kwargs):
    index = target['index']
    new_point = {'start': target['start'],
                 'stop': target['stop'],
                 'name': target['name']}
    del target['start'], target['stop'], target['name'], target['index']
    new_point.update(target)
    labels.insert(index, new_point)

# invert operations

INVERSE_TABLE = {'set_name': 'set_name',
                 'set_start': 'set_start',
                 'set_stop': 'set_stop',
                 'merge_next': 'split',
                 'split': 'merge_next',
                 'delete': 'create',
                 'create': 'delete'}

def invert(s_expr):
    """Generates an s-expression for the inverse of s_expr."""
    op = s_expr[0]
    inverse = INVERSE_TABLE[op]
    target = s_expr[s_expr.index('target') + 1]
    for i in range(len(s_expr)):
        curr = s_expr[i]
        if isinstance(curr, KeyArg) and len(curr) >= 4 and curr[:4] == 'new_':
            oldname = curr[4:]
            oldval = copy.deepcopy(target[target.index(oldname) + 1])
            target[target.index(oldname) + 1] = copy.deepcopy(s_expr[i + 1])
            s_expr[i + 1] = oldval
    inverse_s_expr = [Symbol(inverse)]
    inverse_s_expr.extend(s_expr[1:])
    return inverse_s_expr

# reverse parsing

def detokenize(token_list):
    """Turns a flat list of tokens into a command."""
    cmd = token_list[0]
    for t in token_list[1:]:
        if t != ')' and cmd[-1] != '(':
            cmd += ' '
        cmd += t
    return cmd

def write_to_tokens(ntl):
    """Turns an s-expression into a flat token list."""
    token_list = ['(']
    for t in ntl:
        if isinstance(t, list):
            token_list.extend(write_to_tokens(t))
        else:
            token_list.append(deatomize(t))
    token_list.append(')')
    return token_list

def deatomize(a):
    """Turns an atom into a token."""
    if a is None:
        return 'null'
    elif isinstance(a, Symbol):
        ret = a[0] + a[1:].replace('_', '-')
        if isinstance(a, KeyArg):
            ret = '#:' + ret
        return ret
    elif isinstance(a, str):
        return '"' + a + '"'
    elif isinstance(a, numbers.Number):
        return str(a)
    else:
        raise ValueError('unknown atomic type: ' + str(a))

def deparse(s_expr):
    """Turns an s-expression into a command string."""
    return detokenize(write_to_tokens(s_expr))

# parser & evaluator

class Symbol(str): pass

class KeyArg(Symbol): pass

def tokenize(cmd):
    """Turns a command string into a flat token list."""
    second_pass = []
    in_string = False
    for token in cmd.split():
        num_quotes = token.count('"')
        if num_quotes % 2 == 1 and not in_string: # open quote
            second_pass.append(token)
            in_string = True
        elif num_quotes % 2 == 1 and in_string: # close quote
            second_pass[-1] += ' ' + token
            in_string = False
        elif num_quotes == 0 and in_string: # middle words in quote
            second_pass[-1] += ' ' + token
        else:
            second_pass.append(token)
    third_pass = []
    for token in second_pass:
        if token[0] == '(':
            third_pass.append('(')
            if len(token) > 1:
                third_pass.append(token[1:])
        elif token[-1] == ')':
            ct = token.count(')')
            third_pass.append(token[:-ct])
            for _ in range(ct):
                third_pass.append(')')
        else:
            third_pass.append(token)
    return third_pass


def atomize(token):
    """Turns a token into an atom."""
    if token[0] == '"':
        try:
            return token[1:-1].decode('string_escape')
        except AttributeError: # python 2/3 support
            return token[1:-1]
    if token == 'null':
        return None
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            token = token[0] + token[1:].replace('-', '_')
            if token[:2] == '#:':
                return KeyArg(token[2:])
            return Symbol(token)


def read_from_tokens(token_list):
    """Turns a flat token list into an s-expression."""
    if len(token_list) == 0:
        raise SyntaxError('unexpected EOF')
    token = token_list.pop(0)
    if token == '(':
        nested_list = []
        while token_list[0] != ')':
            nested_list.append(read_from_tokens(token_list))
        token_list.pop(0)
        return nested_list
    elif token == ')':
        raise SyntaxError('unexpected )')
    else:
        return atomize(token)


def parse(cmd):
    """Turns a command string into an s-expression."""
    return read_from_tokens(tokenize(cmd))


def make_env(labels=None, **kwargs):
    """Returns an environment for s-expression evaluation."""
    env = {'set_name': ft.partial(_set_value, labels=labels, column='name'),
           'set_start': ft.partial(_set_value, labels=labels, column='start'),
           'set_stop': ft.partial(_set_value, labels=labels, column='stop'),
           'merge_next': ft.partial(_merge_next, labels=labels),
           'split': ft.partial(_split, labels=labels),
           'delete': ft.partial(_delete, labels=labels),
           'create': ft.partial(_create, labels=labels),
           'interval': dict,
           'interval_pair': dict}
    env['labels'] = labels
    env.update(kwargs)
    return env


def evaluate(expr, env=make_env()):
    """Evaluates an s-expression in the context of an environment."""
    if isinstance(expr, Symbol):
        return env[expr]
    elif not isinstance(expr, list):
        return expr
    else:
        proc = evaluate(expr[0], env)
        kwargs = {p[0]: evaluate(p[1], env) for p in _grouper(expr[1:], 2)}
        return proc(**kwargs)


def _grouper(iterable, n):
    """Returns nonoverlapping windows of input of length n.
    
       Copied from itertools recipe suggestions."""
    args = [iter(iterable)] * n
    try:
        return itertools.izip_longest(*args)
    except AttributeError: # python 2/3 support
        return itertools.zip_longest(*args)
