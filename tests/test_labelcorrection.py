import pytest
import copy
import labelcorrection.labelcorrection as lc
import os
import tempfile
import yaml

TEST_COMMAND = '(set-name (interval 3 4.7 5.0 "d" "focus_bird") "b")'
TEST_LABELS = [{'start': 1.0, 'stop': 2.1, 'name': 'a'},
               {'start': 2.1, 'stop': 3.5, 'name': 'b'},
               {'start': 3.5, 'stop': 4.2, 'name': 'c'},
               {'start': 4.7, 'stop': 5.0, 'name': 'd'}]
TEST_OPS = ["""(set-name #:labels labels
                         #:target (interval #:index 0 #:name "a")
                         #:new-name "q")""",
            """(set-boundary #:labels labels
                             #:target (interval #:index 2 #:bd 4.2)
                             #:which "stop"
                             #:new-bd 4.5)"""]

# test raw label correction operations

def test__set_name():
    labels = copy.deepcopy(TEST_LABELS)
    lc._set_name(labels, {'index': 3}, 'b', discard='spam')
    assert labels[3]['name'] == 'b'

def test__set_bd():
    labels = copy.deepcopy(TEST_LABELS)
    with pytest.raises(KeyError):
        lc._set_bd(labels, {'index': 3}, 'foo', 3.4)
    
    lc._set_bd(labels, {'index': 3}, 'start', 4.6, discard='spam')
    assert round(labels[3]['start'], 2) == 4.6

    lc._set_bd(labels, {'index': 3}, 'stop', 6.4)
    assert round(labels[3]['stop'], 2) == 6.4

def test__merge_next():
    labels = copy.deepcopy(TEST_LABELS)
    lc._merge_next(labels, {'index': 1}, discard='spam', new_name='q')
    assert len(labels) == 3
    assert labels[1]['stop'] == 4.2
    assert labels[1]['name'] == 'q'
    assert labels[2]['name'] == 'd'

def test__split():
    labels = copy.deepcopy(TEST_LABELS)
    with pytest.raises(ValueError):
        lc._split(labels, {'index': 3}, 'd', 1.0, 'e')
    
    lc._split(labels, {'index': 3}, 'd', 4.8, 'e')
    assert len(labels) == 5
    assert labels[3]['stop'] == 4.8
    assert labels[3]['name'] == 'd'
    assert labels[4]['start'] == 4.8
    assert labels[4]['stop'] == 5.0
    assert labels[4]['name'] == 'e'

def test__delete():
    labels = copy.deepcopy(TEST_LABELS)
    lc._delete(labels, {'index': 2})
    assert len(labels) == 3
    assert labels[2]['name'] == 'd'

def test__create():
    labels = copy.deepcopy(TEST_LABELS)
    new_interval = {'index': 2,
                    'start': 3.1,
                    'stop': 3.3,
                    'name': 'c2',
                    'tier': 'female'}
    lc._create(labels, new_interval)
    assert len(labels) == 5
    with pytest.raises(KeyError):
        labels[2]['index']
    assert labels[2]['start'] == 3.1
    assert labels[2]['stop'] == 3.3
    assert labels[2]['name'] == 'c2'
    assert labels[2]['tier'] == 'female'
    assert labels[3]['name'] == 'c'

# test parser functions

def test_tokenize():
    tkns = lc.tokenize(TEST_COMMAND)
    assert len(tkns) == 12
    assert tkns[0] == '('
    assert tkns[5] == '4.7'
    assert tkns[8] == '"focus_bird"'
    assert tkns[11] == ')'
    
    tkns = lc.tokenize('string "spaces preserved"')
    assert len(tkns) == 2
    assert tkns[0] == 'string'
    assert tkns[1] == '"spaces preserved"'

def test_atomize():
    assert lc.atomize('1') == 1
    assert lc.atomize('1.5') == 1.5
    assert lc.atomize('(') == '('
    assert lc.atomize('"focus_bird"') == 'focus_bird'
    assert isinstance(lc.atomize('set-name'), lc.Symbol)
    assert lc.atomize('set-name') == 'set_name'

def test_parse_and_read_from_tokens():
    with pytest.raises(SyntaxError):
        lc.read_from_tokens([])
    
    with pytest.raises(SyntaxError):
        lc.read_from_tokens([')'])
    
    nested_list = lc.parse(TEST_COMMAND)
    assert len(nested_list) == 3
    assert len(nested_list[1]) == 6
    assert nested_list[0] == 'set_name'
    assert nested_list[1][0] == 'interval'
    assert nested_list[1][5] == 'focus_bird'

def test_evaluate():
    def complex_proc(**kwargs):
        for a in kwargs:
            if isinstance(kwargs[a], float):
                kwargs[a] += 1.0
        return kwargs
    test_env = {'symbol': 'answer',
                'simple_proc': dict,
                'complex_proc': complex_proc}
    
    assert lc.evaluate(lc.Symbol('symbol'), test_env) == 'answer'
    
    assert lc.evaluate(1.5, test_env) == 1.5
    
    expr = [lc.Symbol('simple_proc'),
            lc.KeyArg('start'), 1.5,
            lc.KeyArg('stop'), 2.0,
            lc.KeyArg('name'), 'a']
    result = lc.evaluate(expr, test_env)
    assert isinstance(result, dict)
    assert result['start'] == 1.5
    assert result['stop'] == 2.0
    assert result['name'] == 'a'
    
    expr[0] = lc.Symbol('complex_proc')
    result = lc.evaluate(expr, test_env)
    assert isinstance(result, dict)
    assert result['start'] == 2.5
    assert result['stop'] == 3.0
    assert result['name'] == 'a'

def test_whole_stack():
    labels = copy.deepcopy(TEST_LABELS)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = """(set-name #:labels labels
                       #:target (interval #:index 0 #:name "a")
                       #:new-name "b")"""
    lc.evaluate(lc.parse(cmd), test_env)
    assert labels[0]['name'] == 'b'
    
    cmd = """(set-boundary #:labels labels
                           #:target (interval #:index 1 #:bd 3.141)
                           #:which "start"
                           #:new-bd 2.2)"""
    lc.evaluate(lc.parse(cmd), test_env)
    assert labels[1]['start'] == 2.2
    
    cmd = """(merge-next #:labels labels
                         #:target (interval-pair #:index 1
                                                 #:name "b"
                                                 #:sep 3.240
                                                 #:next-name "silence")
                         #:new-name null
                         #:new-sep null
                         #:new-next-name null)"""
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == len(TEST_LABELS) - 1
    assert labels[1]['stop'] == TEST_LABELS[2]['stop']
    
    cmd = """(split #:labels labels
                    #:target (interval-pair #:index 1
                                            #:name null
                                            #:sep null
                                            #:next-name null)
                    #:new-name "b"
                    #:new-sep 3.5
                    #:new-next-name "c")"""
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == len(TEST_LABELS)
    assert labels[1]['stop'] == TEST_LABELS[1]['stop']

# test inverse parser operations and inverse generator

def test_deatomize():
    assert lc.deatomize(None) == 'null'
    
    assert lc.deatomize(lc.KeyArg('name')) == '#:name'
    
    assert lc.deatomize(lc.Symbol('split')) == 'split'
    assert lc.deatomize(lc.Symbol('merge_next')) == 'merge-next'
    assert lc.deatomize(lc.Symbol('_')) == '_'
    
    assert lc.deatomize('b') == '"b"'
    
    assert lc.deatomize(1.5) == '1.5'
    
    with pytest.raises(ValueError):
        lc.deatomize(ValueError)

def test_detokenize():
    token_list = ['(', 'merge-next', '#:target', '(',
                  'interval-pair', '#:index', '0', '#:name', 'null',
                   '#:sep', 'null', '#:next-name', 'null', ')',
                  '#:new-name', '"b"', '#:new-sep', '1.5',
                  '#:new-next-name', '"c"', ')']
    cmd = lc.detokenize(token_list)
    assert isinstance(cmd, str)
    assert cmd[0] == '('
    assert cmd[-1] == ')'
    assert cmd[12:20] == '#:target'
    ident = lc.tokenize(cmd)
    assert token_list == ident

def test_write_to_tokens():
    expr = [lc.Symbol('merge_next'), lc.KeyArg('target'),
            [lc.Symbol('interval_pair'), lc.KeyArg('index'), 0,
             lc.KeyArg('name'), None, lc.KeyArg('sep'), None,
             lc.KeyArg('next_name'), None],
            lc.KeyArg('new_name'), "b", lc.KeyArg('new_sep'), 1.5,
            lc.KeyArg('new_next_name'), "c"]
    token_list = lc.write_to_tokens(expr)
    assert token_list[0] == '('
    assert token_list[-1] == ')'
    assert token_list[3] == '('
    assert token_list[13] == ')'
    assert token_list[-3] == '#:new-next-name'
    assert token_list[-2] == '"c"'
    ident = lc.read_from_tokens(token_list)
    assert expr == ident

def test_invert():
    cmd = '(merge-next #:target (interval-pair #:index 0 #:name null #:sep null #:next-name null) #:new-name "b" #:new-sep 1.5 #:new-next-name "c")'
    hand_inv = '(split #:target (interval-pair #:index 0 #:name "b" #:sep 1.5 #:next-name "c") #:new-name null #:new-sep null #:new-next-name null)'
    inv = lc.invert(cmd)
    assert inv == hand_inv
    
    ident = lc.invert(lc.invert(cmd))
    assert cmd == ident

# test CorrectionStack methods

def make_corr_file(tmpdir):
    tf = tempfile.NamedTemporaryFile(mode='w', dir=tmpdir.strpath, delete=False)
    tf.write("""# corrections, YAML\n---\n""")
    file_data = {'uuid': '0',
                 'operations': TEST_OPS,
                 'label_file': 'not/a/real/file'}
    tf.write(yaml.safe_dump(file_data))
    tf.close()
    return tf

def test_CS_init(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    
    cs = lc.CorrectionStack(labels=labels, dir=tmpdir.strpath)
    assert cs.labels == labels
    assert os.path.exists(cs.corr_file)
    assert cs.corr_file[-5:] == '.corr'
    
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name)
    assert cs.labels == TEST_LABELS
    assert cs.corr_file == tf.name
    assert os.path.exists(cs.corr_file)
    assert len(cs.stack) == 2
    assert cs.stack[0] == TEST_OPS[0]
    assert cs.stack[1] == TEST_OPS[1]
    assert cs.uuid == '0'
    assert cs.pc == 1
    assert cs.written == cs.pc
    assert cs.dirty == False
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    assert cs.corr_file == tf.name
    assert cs.pc == len(cs.stack) - 1
    assert cs.written == cs.pc
    assert cs.dirty == False
    assert cs.labels[1] == TEST_LABELS[1]
    assert cs.labels[3] == TEST_LABELS[3]
    assert cs.labels[0]['name'] == 'q'
    assert cs.labels[2]['stop'] == 4.5
    
    os.remove(tf.name)

def test_CS_read_from_file(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, dir=tmpdir.strpath)
    cs.read_from_file(tf.name)
    assert cs.pc == 1
    assert cs.written == 1
    assert cs.dirty == False
    assert cs.labels == TEST_LABELS
    assert cs.stack == TEST_OPS
    
    cs.read_from_file(tf.name, already_applied=False)
    assert cs.pc == -1
    assert cs.written == 1
    assert cs.dirty == False
    assert cs.labels == TEST_LABELS
    assert cs.stack == TEST_OPS
    
    os.remove(tf.name)

def test_CS_write_to_file(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    new_cmd = """(set-name #:labels labels
                           #:target (interval #:index 1 #:name "b")
                           #:new-name "z")"""
    cs.push(new_cmd)
    os.remove(tf.name)
    cs.write_to_file()
    cs_new = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    assert len(cs_new.stack) == 3
    assert cs_new.stack == cs.stack
    assert cs_new.stack[-1] == new_cmd
    assert cs_new.label_file == cs.label_file
    assert cs_new.uuid == cs.uuid
    
    os.remove(tf.name)

def test_CS_undo_and_redo(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    new_cmd = """(set-name #:labels labels
                           #:target (interval #:index 1 #:name "b")
                           #:new-name "z")"""
    cs.push(new_cmd)
    assert cs.labels[1]['name'] == "z"
    assert cs.labels[2]['stop'] == 4.5
    assert cs.labels[0]['name'] == "q"

    cs.undo() # undo new_cmd
    assert cs.pc == len(cs.stack) - 2
    assert cs.written == len(cs.stack) - 2
    assert cs.dirty == False
    assert cs.labels[1]['name'] == "b"
    assert cs.labels[2]['stop'] == 4.5
    assert cs.labels[0]['name'] == "q"
    
    cs.undo() # undo TEST_OPS[1]
    assert cs.pc == len(cs.stack) - 3
    assert cs.written == len(cs.stack) - 2
    assert cs.dirty == True
    assert cs.labels[1]['name'] == "b"
    assert cs.labels[2]['stop'] == 4.2
    assert cs.labels[0]['name'] == "q"
    
    cs.undo() # undo TEST_OPS[0]
    cs.undo() # undo actions when at tail do nothing
    cs.undo()
    assert cs.pc == -1
    assert cs.written == len(cs.stack) - 2
    assert cs.dirty == True
    assert cs.labels[1]['name'] == "b"
    assert cs.labels[2]['stop'] == 4.2
    assert cs.labels[0]['name'] == "a"
    
    cs.redo() # redo TEST_OPS[0]
    assert cs.pc == 0
    assert cs.written == len(cs.stack) - 2
    assert cs.dirty == True
    assert cs.labels[1]['name'] == "b"
    assert cs.labels[2]['stop'] == 4.2
    assert cs.labels[0]['name'] == "q"
    
    cs.redo() # redo TEST_OPS[1]
    assert cs.pc == 1
    assert cs.written == len(cs.stack) - 2
    assert cs.dirty == True
    assert cs.labels[1]['name'] == "b"
    assert cs.labels[2]['stop'] == 4.5
    assert cs.labels[0]['name'] == "q"

    cs.redo() # redo new_cmd
    cs.redo() # redo actions when at head do nothing
    cs.redo()
    assert cs.pc == 2
    assert cs.written == len(cs.stack) - 2
    assert cs.dirty == True
    assert cs.labels[1]['name'] == "z"
    assert cs.labels[2]['stop'] == 4.5
    assert cs.labels[0]['name'] == "q"

    os.remove(tf.name)

def test_CS_push(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    assert cs.labels[1]['name'] == "b"
    assert cs.labels[2]['stop'] == 4.5
    assert cs.labels[0]['name'] == "q"

    new_cmd = """(set-name #:labels labels
                           #:target (interval #:index 1 #:name "b")
                           #:new-name "z")"""
    cs.push(new_cmd) # push adds new_cmd to head of stack
    assert cs.labels[1]['name'] == "z"
    assert cs.labels[2]['stop'] == 4.5
    assert cs.labels[0]['name'] == "q"
    
    cs.undo()
    cs.undo()
    cs.push(new_cmd) # TEST_OPS[1] is gone; new_cmd now at head of stack
    assert len(cs.stack) == 2
    assert cs.labels[1]['name'] == "z"
    assert cs.labels[2]['stop'] == 4.2
    assert cs.labels[0]['name'] == "q"
    
    os.remove(tf.name)

def test_CS_peek(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    p = cs.peek() # default is to show op at pc, which is last one applied
    assert p == TEST_OPS[1]
    
    p = cs.peek(len(cs.stack) + 10) # peeking past head returns None
    assert p is None
    
    p = cs.peek(-10) # peeking before tail returns None
    assert p is None
    
    p = cs.peek(0)
    assert p == TEST_OPS[0]
    
    os.remove(tf.name)

def test_CS__apply(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)
    
    cs = lc.CorrectionStack(labels=labels, corr_file=tf.name, apply=True)
    new_cmd = """(set-name #:labels labels
                           #:target (interval #:index 1 #:name "b")
                           #:new-name "z")"""
    cs._apply(new_cmd)
    # this screws up the pc tracking - the stack is now in an undefined state
    # but we can still check that _apply performed the new_cmd operation
    assert cs.labels[1]['name'] == 'z'
    
    os.remove(tf.name)

def test_CS_redo_all(tmpdir):
    labels = copy.deepcopy(TEST_LABELS)
    tf = make_corr_file(tmpdir)

    cs = lc.CorrectionStack(labels=labels, dir=tmpdir.strpath)
    cs.read_from_file(tf.name, already_applied=False)
    # none of the stack 
    assert cs.labels[0]['name'] == TEST_LABELS[0]['name'] # 'a'
    assert cs.labels[2]['stop'] == TEST_LABELS[2]['stop'] # 4.2
    
    cs.redo_all()
    assert cs.labels[0]['name'] == 'q'
    assert cs.labels[2]['stop'] == 4.5
    
    os.remove(tf.name)

# test code generators

def test_cg_rename():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.rename(0, 'q')
    lc.evaluate(lc.parse(cmd), test_env)
    assert labels[0]['name'] == 'q'

def test_cg_set_start():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.set_start(0, 1.6)
    lc.evaluate(lc.parse(cmd), test_env)
    assert labels[0]['start'] == 1.6

def test_cg_set_stop():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.set_stop(0, 1.8)
    lc.evaluate(lc.parse(cmd), test_env)
    assert labels[0]['stop'] == 1.8

def test_cg_merge_next():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.merge_next(0, new_name='q')
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == 3
    assert labels[0]['start'] == 1.0
    assert labels[0]['stop'] == 3.5
    assert labels [0]['name'] == 'q'
    
    cmd = cs.merge_next(0)
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == 2
    assert labels[0]['name'] == 'qc'

def test_cg_split():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.split(0, 1.8, 'a1', 'a2')
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == 5
    assert labels[0]['start'] == 1.0
    assert labels[0]['stop'] == 1.8
    assert labels[0]['name'] == 'a1'
    assert labels[1]['start'] == 1.8
    assert labels[1]['stop'] == 2.1
    assert labels[1]['name'] == 'a2'
    
    cmd = cs.split(0, 1.5)
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == 6
    assert labels[0]['name'] == 'a1'
    assert labels[1]['name'] == ''

def test_cg_delete():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.delete(0)
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == 3
    assert labels[0]['start'] == 2.1
    assert labels[0]['stop'] == 3.5
    assert labels[0]['name'] == 'b'

def test_cg_create():
    labels = copy.deepcopy(TEST_LABELS)
    cs = lc.CorrectionStack(labels=labels, no_file=True)
    test_env = lc.lc_env()
    test_env.update({'labels': labels})
    
    cmd = cs.create(0, 0.5, stop=0.9, name='q', tier='spam')
    lc.evaluate(lc.parse(cmd), test_env)
    assert len(labels) == 5
    assert labels[0]['start'] == 0.5
    assert labels[0]['stop'] == 0.9
    assert labels[0]['name'] == 'q'
    assert labels[0]['tier'] == 'spam'
    assert labels[1] == TEST_LABELS[0]