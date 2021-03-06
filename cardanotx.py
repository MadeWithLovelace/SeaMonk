#!/usr/bin/python
import os
import subprocess
import json
import hashlib
import base64
import requests
from time import sleep, strftime, gmtime

#Load Settings
settings_file = os.path.join(os.path.realpath(os.path.dirname(__file__)), '') + 'profile.json'
is_settings_file = os.path.isfile(settings_file)
if is_settings_file:
    s = json.load(open(settings_file, 'r'))

def set_vars(profile_name):
    # Defaults and overrides
    if type(profile_name) is list:
        cli = profile_name[0]
        network = profile_name[1]
        magic = profile_name[2]
        log = profile_name[3]
        txlog = profile_name[4]
        cache = profile_name[5]
        if network == 'testnet-magic':
            testnet = True
        else:
            testnet = False
    else:
        log = s[profile_name]['log']
        txlog = s[profile_name]['txlog']
        cache = s[profile_name]['cache']
        cli = s[profile_name]['cli_path']
        network = s[profile_name]['network']
        magic = s[profile_name]['magic']
        testnet = False
        if network == 'testnet-magic':
            testnet = True
    return cli, network, magic, log, cache, txlog, testnet

def get_token_identifier(policy_id, token_name):
    """
    Takes the blake2b hash of the concat of the policy ID and token name.
    """
    hex_name = base64.b16encode(bytes(str(token_name).encode('utf-8'))).lower()
    b_policy_id = bytes(str(policy_id).encode('utf-8'))
    concat = b_policy_id+hex_name
    h = hashlib.blake2b(digest_size=20)
    h.update(concat)
    return h.hexdigest()

def get_tx_hash(profile_name, filePre):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'transaction',
        'txid',
        '--tx-file',
        txlog + filePre + 'tx.signed'
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

def get_hash_value(profile_name, value):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'transaction',
        'hash-script-data',
        '--script-data-value',
        value
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

def process_tokens(profile_name, tokens, wallet_addr, amnt='all', return_ada='2000000', exclude='', flag=True):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    if len(tokens) > 1:
        utxo_string = get_utxo_string(tokens, amnt, exclude, flag)
        if len(utxo_string) != 0:
            #minimum_cost = find_min(profile_name, cache, utxo_string) -> Was +str(minimum_cost) blow where return_ada is TODO Fix this function
            return ['--tx-out', wallet_addr+"+"+return_ada+"+"+utxo_string]
        else:
            return []
    else:
        return []

def find_min(profile_name, cache, utxo_string):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'transaction',
        'calculate-min-value',
        '--protocol-params-file',
        cache + 'protocol.json',
        '--multi-asset',
        utxo_string
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    try:
        p.split(' ')[1].replace('\n', '')
    except IndexError:
        p = 2000000
    return p

def get_utxo_string(tokens, amnt, exclude=[], flag=True):
    utxo_string = ''
    for token in tokens:
        if token == 'lovelace':
            continue
        for t_qty in tokens[token]:
            if amnt == 'all':
                quant = str(tokens[token][t_qty])
            else:
                quant = str(amnt)
            if len(exclude) != 0:
                if flag is True:
                    if t_qty not in exclude and token not in exclude:
                        utxo_string += quant + ' ' + token + '.' + t_qty + '+'
                else:
                    if t_qty in exclude and token in exclude:
                        utxo_string += quant + ' ' + token + '.' + t_qty + '+'
            else:
                utxo_string += quant + ' ' + token + '.' + t_qty + '+'
    return utxo_string[:-1]

def get_address_pubkeyhash(cli_path, vkey_path):
    func = [
        cli_path,
        'address',
        'key-hash',
        '--payment-verification-key-file',
        vkey_path
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

def get_token_id(profile_name, out_script):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'transaction',
        'policyid',
        '--script-file',
        out_script
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

def get_wallet_addr(profile_name, vkey_path):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'address',
        'build',
        '--' + network,
        '--payment-verification-key-file',
        vkey_path
    ]
    if testnet:
        func.insert(4, magic)
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

def get_smartcontract_addr(profile_name, smartcontract_path):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'address',
        'build',
        '--' + network,
        '--payment-script-file',
        smartcontract_path
    ]
    if testnet:
        func.insert(4, magic)
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

def check_for_tx(profile_name, tx_hash_match):
    """
    Checks for a matching transaction
    """
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'
    txlog_file = log + 'transactions.log'
    is_txlog_file = os.path.isfile(txlog_file)
    if not is_txlog_file:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nERROR tying to open txlog file')
            runlog.close()
        return False
    # Look for tx_hash_match in tx log file
    txlog_r = open(txlog_file, 'r')
    with open(txlog_file, 'r') as txlog_r:
        readtx_index = 0
        for x in txlog_r:
            if readtx_index == 0:
                readtx_index += 1
                continue
            readtx_index += 1
            cells = x.split(',')
            tx_hash = cells[0]
            if tx_hash_match == tx_hash:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nMatching TX found, returning True: '+tx_hash_match+' | '+tx_hash)
                    runlog.close()
                txlog_r.close()
                return True
    txlog_r.close()
    return False

def log_new_txs(profile_name, api_id, wallet_addr):
    """
    Checks for new transactions and maintains a log of tx_hashes at seamonk-data/transactions.log, returns new tx count integer
    """
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'

    # Setup file
    txcount = 0
    txlog_file = log + 'transactions.log'
    is_log_file = os.path.isfile(txlog_file)
    if not is_log_file:
        try:
            open(txlog_file, 'x')
            with open(txlog_file, 'a') as txlog_header:
                txlog_header.write('UTxO_Hash,' + 'FromAddr,' + 'Amount' + '\n')
                txlog_header.close()
        except OSError:
            pass
        
    # Get UTXO Info
    tx_list = [
        cardano_cli,
        'query',
        'utxo',
        '--' + network,
        '--address',
        wallet_addr
    ]
    if testnet:
        tx_list.insert(4, magic)
    rawUtxoTable = subprocess.check_output(tx_list)
    # Output rows
    utxoTableRows = rawUtxoTable.strip().splitlines()
    # Foreach row compare against each line of tx file
    for x in range(2, len(utxoTableRows)):
        cells = utxoTableRows[x].split()
        tx_hash = cells[0].decode('utf-8')
        txlog_r = open(txlog_file, 'r')
        flag = 0
        index = 1
        # Foreach line of the file
        for line in txlog_r:
            index += 1
            if tx_hash in line:
                flag = 1
                txlog_r.close()
                break
        if flag == 1:
            continue
        if flag == 0:
            with open(txlog_file, 'a') as txlog_a:
                # Get curl data from blockfrost on new tx's only
                headers = {'project_id': api_id}
                cmd = s[profile_name]['api_uri'] + 'txs/' + tx_hash + '/utxos'
                tx_result = requests.get(cmd, headers=headers)
                
                # Check if hash found at api
                if 'status_code' in tx_result.json():
                    status_code = tx_result.json()['status_code']
                    txlog_a.close()
                    continue
                for tx_data in tx_result.json()['inputs']:
                    from_addr = tx_data['address']
                for output in tx_result.json()['outputs']:
                    if output['address'] == wallet_addr:
                        for amounts in output['amount']:
                            if amounts['unit'] == 'lovelace':
                                txcount += 1
                                pay_amount = amounts['quantity']
                                txlog_a.write(tx_hash + ',' + from_addr + ',' + str(pay_amount) + '\n')
                txlog_a.close()
            txlog_r.close()
    return txcount

def check_for_payment(profile_name, api_id, wallet_addr, amount = 0, min_watch = 0, sender_addr = 'none'):
    """
    Checks for an expected amount of ADA from any address in a whitelist (or specific passed) and maintains a log of expected and any other present UTxO payments in profile-specific payments.log file
    """
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'

    # Setup file
    watch_addr = s[profile_name]['watchaddr']
    sc_addr = s[profile_name]['scaddr']
    amount = int(amount)
    min_watch = int(min_watch)
    compare_addr = True
    compare_amnt = True
    record_as_payment = False
    if sender_addr == 'none':
        compare_addr = False
    if amount == 0 and min_watch == 0:
        compare_amnt = False
    return_data = ''
    payments_file = log + 'payments.log'
    txlog_file = log + 'transactions.log'
    is_paymentlog_file = os.path.isfile(payments_file)
    # if no txlog, run an instance of the transaction getter
    is_txlog_file = os.path.isfile(txlog_file)
    if not is_txlog_file:
        try:
            log_new_txs(profile_name, api_id, wallet_addr)
        except OSError:
            pass

    if not is_paymentlog_file:
        try:
            open(payments_file, 'x')
            with open(payments_file, 'a') as payments_header:
                payments_header.write('UTxO_Hash,' + 'FromAddr,' + 'Amount\n')
                payments_header.close()
        except OSError:
            pass
    
    # Foreach tx_log row compare against each line of payments_log
    txlog_r = open(txlog_file, 'r')
    with open(txlog_file, 'r') as txlog_r:
        readtx_index = 0
        for x in txlog_r:
            if readtx_index == 0:
                readtx_index += 1
                continue
            readtx_index += 1
            cells = x.split(',')
            tx_hash = cells[0]
            tx_addr = cells[1]
            tx_amnt = int(cells[2])
            flag = 0
            readpay_index = 0
            payments_r = open(payments_file, 'r')
            # Foreach line of the file
            for line in payments_r:
                if readpay_index == 0:
                    readpay_index += 1
                    continue
                readpay_index += 1
                if tx_hash in line:
                    flag = 1
                    break
            if tx_addr == watch_addr or tx_addr == sc_addr:
                flag = 1
            if flag == 1:
                continue
            if flag == 0:
                if len(sender_addr) == 103:
                    sender_addr = sender_addr[52:-6]
                    tx_addr = tx_addr[52:-6]
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\n--- Long Address Detected, Trimming: ---\n' + sender_addr + ' | ' + tx_addr + '\n-----------------------------------\n')
                        runlog.close()
                if compare_addr == True and compare_amnt == True:
                    if tx_addr == sender_addr:
                        if min_watch > 0 and tx_amnt >= min_watch:
                            record_as_payment = True
                        elif tx_amnt == amount:
                            record_as_payment = True
                        else:
                            record_as_payment = False
                elif compare_addr == True:
                    if tx_addr == sender_addr:
                        record_as_payment = True
                    else:
                        record_as_payment = False
                elif compare_amnt == True:
                    if min_watch > 0 and tx_amnt >= min_watch:
                        record_as_payment = True
                    elif tx_amnt == amount:
                        record_as_payment = True
                    else:
                        record_as_payment = False
                else:
                    record_as_payment = True
                if record_as_payment == True:
                    return_data = tx_hash + ',' + tx_addr + ',' + str(tx_amnt)
            record_as_payment = False
            payments_r.close()
    if len(return_data) > 1:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\n--- Check For Payments Result:: ---\n' + return_data)
            runlog.close()
    txlog_r.close()
    return return_data

def clean_folder(profile_name):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    from os import remove
    from glob import glob
    files = glob(cache + '*')
    for f in files:
        remove(f)

def proto(profile_name):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'query',
        'protocol-parameters',
        '--' + network,
        '--out-file',
        cache + 'protocol.json'
    ]
    if testnet:
        func.insert(4, magic)
    p = subprocess.Popen(func)
    p.communicate()

def get_utxo(profile_name, token_wallet, file_name):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'query',
        'utxo',
        '--' + network,
        '--address',
        token_wallet,
        '--out-file',
        cache + file_name
    ]
    if testnet:
        func.insert(4, magic)
    p = subprocess.Popen(func)
    p.communicate()

def get_txin(profile_name, file_name, collateral, spendable = False, allowed_datum = '', check_amnt = 0):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'
    if check_amnt > 0:
        check_amnt = int(check_amnt)
    check_price_found = False
    utxo_ada_sum = 0
    txin_list = []
    data_list = {}
    txincollat_list = []
    amount = {}
    counter = 0
    with open(cache+file_name, "r") as read_content:
        data = json.load(read_content)
    # store all tokens from utxo
    for d in data:
        # Store all the data
        try:
            data_list[d] = data[d]['data']
        except KeyError:
            pass
        # Get the token
        for token in data[d]['value']:
            # Check for the ADA collateral on ADA-only UTxOs
            tokencount = len(data[d]['value'])
            if token == 'lovelace' and tokencount == 1:
                if check_amnt > 0:
                    utxo_ada_sum += int(data[d]['value'][token])
                if data[d]['value'][token] == collateral:
                    txincollat_list.append('--tx-in-collateral')
                    txincollat_list.append(d)
            # Get all the tokens
            if token in amount.keys():
                if token == 'lovelace':
                    amount[token] += data[d]['value'][token]
                else:
                    if spendable is True:
                        pass
                    else:
                        for t_qty in data[d]['value'][token]:
                            try:
                                amount[token][t_qty] += data[d]['value'][token][t_qty]
                            except KeyError:
                                amount[token][t_qty] = data[d]['value'][token][t_qty]
            else:
                if token == 'lovelace':
                    amount[token] = data[d]['value'][token]
                else:
                    if spendable is True:
                        try:
                            if data[d]['data'] == allowed_datum:
                                amount[token] = data[d]['value'][token]
                        except KeyError:
                            pass
                    else:
                        amount[token] = data[d]['value'][token]
        # Build string
        txin_list.append('--tx-in')
        txin_list.append(d)
        # Increment the counter
        counter += 1
    if check_amnt > 0:
        if utxo_ada_sum >= check_amnt:
            check_price_found = True
        return check_price_found
    if counter == 1:
        return txin_list, txincollat_list, amount, False, data_list
    return txin_list, txincollat_list, amount, True, data_list

def get_tip(profile_name, add_slots = 1000):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)
    func = [
        cardano_cli,
        'query',
        'tip',
        '--' + network,
        '--out-file',
        cache + 'latest_tip.json'
    ]
    if testnet:
        func.insert(4, magic)
    p = subprocess.Popen(func)
    p.communicate()
    with open(cache+"latest_tip.json", "r") as tip_data:
        td = json.load(tip_data)
    return int(td['slot']), int(td['slot']) + add_slots, int(td['block'])

def build_tx(profile_name, change_addr, until_tip, utxo_in, utxo_col, utxo_out, tx_data, manual = False):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'
    func = [
        cardano_cli,
        'transaction',
        'build',
        '--alonzo-era',
        '--cardano-mode',
        '--' + network,
        '--protocol-params-file',
        cache+'protocol.json',
        '--change-address',
        change_addr,
        '--invalid-hereafter',
        str(until_tip),
        '--out-file',
        cache+'tx.draft'
    ]
    if testnet:
        func.insert(6, magic)
    func += utxo_in
    func += utxo_col
    func += utxo_out
    func += tx_data
    if manual:
        print('\n================================= TX Built =================================')
        print('\nCheck transaction details and approve before submitting to the blockchain:\n')
        print('\n----------------------------------------------------------------------------')
        joined_func_out = ' '.join(func)
        print(joined_func_out)
        print('\n----------------------------------------------------------------------------')
        VALUES_CORRECT = input('\n\nMint this? (enter yes or no):')
        if VALUES_CORRECT == ('yes'):
            print('\n\nContinuing . . . \n')
        else:
            print('\n\nQuitting . . .\n\n')
            exit(0)
    with open(runlog_file, 'a') as runlog:
        time_now = strftime("%Y-%m-%d %H:%M:%S", gmtime())
        runlog.write('\nTX at: ' + time_now)
        runlog.write('\n-----------------TX Built--------------------\n')
        joined_func = ' '.join(func)
        runlog.write(joined_func)
        runlog.write('\n-------------------End------------------\n')
        runlog.close()
    p = subprocess.Popen(func)
    p.communicate()

def sign_tx(profile_name, witnesses, filePre):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'
    func = [
        cardano_cli,
        'transaction',
        'sign',
        '--tx-body-file',
        cache + 'tx.draft',
        '--' + network,
        '--tx-file',
        txlog + filePre + 'tx.signed'
    ]
    if testnet:
        func.insert(6, magic)
    func += witnesses
    p = subprocess.Popen(func)
    p.communicate()

def submit_tx(profile_name, filePre):
    # Defaults and overrides
    cardano_cli, network, magic, log, cache, txlog, testnet = set_vars(profile_name)

    # Begin log file
    runlog_file = log + 'run.log'
    func = [
        cardano_cli,
        'transaction',
        'submit',
        '--cardano-mode',
        '--' + network,
        '--tx-file',
        txlog + filePre + 'tx.signed',
    ]
    if testnet:
        func.insert(5, magic)
    p = subprocess.Popen(func)
    p.communicate()
