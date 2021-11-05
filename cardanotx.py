#!/usr/bin/python
import os
import subprocess
import json
import hashlib
import base64
import requests
from time import sleep, strftime, gmtime

def subp_proc(list, log):
    runlog_file = log + 'run.log'
    while True:
        try:
            return subprocess.check_output(list)
            break
        except subprocess.CalledProcessError as e:
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nError in subprocess')
                runlog.close()
            pass
        sleep(2)

def get_token_string_id(full_token):
    t = full_token.split('.')
    hex_name = base64.b16encode(bytes(str(t[1]).encode('utf-8'))).lower()
    return t[0] + hex_name.decode('utf-8')

def encode_to_base64(file_path, type, chunkify = True):
    if type == 'html':
        pre = 'data:text/html;base64,'
    if type == 'svg':
        pre = 'data:image/svg+xml;base64,'
    with open(file_path, 'r') as html:
        html_string = html.read()
        html_result = pre + base64.b64encode(bytes(html_string, 'utf-8')).decode('utf-8').strip()
        if chunkify:
            x = 64
            html_result = [html_result[y-x:y] for y in range(x, len(html_result)+x,x)]
    return html_result

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

def get_tx_hash(default_settings, filePre):
    # Defaults settings
    cardano_cli = default_settings[2]
    txlog = default_settings[7]

    func = [
        cardano_cli,
        'transaction',
        'txid',
        '--tx-file',
        txlog + filePre + 'tx.signed'
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p.strip()

def get_hash_value(default_settings, value):
    # Defaults settings
    cardano_cli = default_settings[2]

    func = [
        cardano_cli,
        'transaction',
        'hash-script-data',
        '--script-data-value',
        value
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p

# TODO: Fix find_min function and/or place multiple assets and seperate UTxOs after reaching a limit
def process_tokens(default_settings, tokens, wallet_addr, amnt = ['all'], return_ada = '2000000', exclude = '', flag = True, calc_ada = False, reserve = 2000000):
    if len(tokens) > 1:
        utxo_string = get_utxo_string(tokens, amnt, exclude, flag)
        if len(utxo_string) != 0:
            #minimum_cost = find_min(default_settings, utxo_string) -> Was +str(minimum_cost) blow where return_ada is TODO Fix this function
            # TODO: refine this section and the else next section
            if calc_ada == True:
                utxo_int = get_utxo_string(tokens, amnt, exclude, flag, calc_ada)
                if utxo_int > 0:
                    utxo_int = utxo_int - int(reserve)
                    return ['--tx-out', wallet_addr+"+"+str(utxo_int)+"+"+utxo_string]
            else:
                return ['--tx-out', wallet_addr+"+"+return_ada+"+"+utxo_string]
        else:
            return []
    else:
        if calc_ada == True:
            utxo_int = get_utxo_string(tokens, amnt, exclude, flag, calc_ada)
            if utxo_int > 0:
                utxo_int = utxo_int - int(reserve)
                return ['--tx-out', wallet_addr+"+"+str(utxo_int)]
        return []

def find_min(default_settings, utxo_string):
    # Defaults settings
    cardano_cli = default_settings[2]
    cache = default_settings[6]

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

def get_utxo_string(tokens, amnt, exclude=[], flag=True, calc_ada = False):
    utxo_string = ''
    if calc_ada == True:
        quant = 0
        for lovelace in tokens:
            if lovelace == 'lovelace':
                quant += int(tokens[lovelace])
        return quant
    for token in tokens:
        if token == 'lovelace':
            continue
        for t_qty in tokens[token]:
            if amnt[0] == 'all':
                quant = str(tokens[token][t_qty])
            elif amnt[0] == 'except':
                qbal = int(tokens[token][t_qty]) - int(amnt[1])
                quant = str(qbal)
            else:
                quant = str(amnt[0])
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
    return p.strip()

def get_token_id(default_settings, out_script):
    # Defaults settings
    cardano_cli = default_settings[2]

    func = [
        cardano_cli,
        'transaction',
        'policyid',
        '--script-file',
        out_script
    ]
    p = subprocess.Popen(func, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    return p.strip()

def get_wallet_addr(default_settings, vkey_path):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    testnet = default_settings[8]

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

def get_smartcontract_addr(default_settings, smartcontract_path):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    testnet = default_settings[8]

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

def archive_tx(default_settings, custom_settings):
    # Defaults settings
    log = default_settings[5]
    txlog = default_settings[7]

    # Custom settings
    tx_hash = custom_settings[0]
    tx_amnt = custom_settings[1]
    tx_time = custom_settings[2]

    # Setup archive file first time
    tx_archive_file = log + 'tx_archive.log'
    is_log_file = os.path.isfile(tx_archive_file)
    if not is_log_file:
        try:
            open(tx_archive_file, 'x')
            with open(tx_archive_file, 'a') as txlog_header:
                txlog_header.write('UTxO_Hash,' + 'FromAddr,' + 'Amount,' + 'TAmount,' + 'Token,' + 'Time\n')
                txlog_header.close()
        except OSError:
            pass
 
    transactions_file = log + 'transactions.log'
    with open(transactions_file,'r') as read_file:
        lines = read_file.readlines()
        currentLine = 0
    with open(transactions_file,'w') as write_file:
        for line in lines:
            line_list = line.split(',')
            if line_list[2] == 'Amount':
                write_file.write(line)
            else:
                hashL = line_list[0].strip()
                amntL = int(line_list[2].strip())
                timeL = line_list[5].strip()
                hashP = tx_hash.strip()
                amntP = int(tx_amnt)
                timeP = tx_time.strip()
                if hashL == hashP and amntP == 0 and timeP == 'none':
                    with open(tx_archive_file, 'a') as archive_file:
                        archive_file.write(line)
                        archive_file.close()
                elif hashL == hashP and amntL == amntP and timeL == timeP:
                    with open(tx_archive_file, 'a') as archive_file:
                        archive_file.write(line)
                        archive_file.close()
                else:
                    write_file.write(line)
                
    read_file.close()
    write_file.close()

def check_for_tx(default_settings, tx_hash_match):
    """
    Checks for a matching transaction
    """
    # Defaults settings
    log = default_settings[5]
    txlog = default_settings[7]

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

def log_new_txs(default_settings, custom_settings):
    """
    Checks for new transactions and maintains a log of tx_hashes at seamonk-data/transactions.log, returns new tx count integer
    """    
    # Defaults settings
    profile_type = default_settings[1]
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    log = default_settings[5]
    testnet = default_settings[8]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    wallet_addr = custom_settings[2]
    fee_token_string = custom_settings[3] # default fee_token_string = ''

    # Begin log file
    runlog_file = log + 'run.log'
    time_now = strftime("%Y-%m-%d %H:%M:%S", gmtime())
    # Debug
    #print('\nLogger Running at ' + time_now)
    #with open(runlog_file, 'a') as runlog:
    #    runlog.write('\nTX Logger Running at ' + time_now)
    #    runlog.close()

    # Setup files
    tx_archive_exist = False
    tx_archive_file = log + 'tx_archive.log'
    txa_is = os.path.isfile(tx_archive_file)

    txcount = 0
    txlog_file = log + 'transactions.log'
    is_log_file = os.path.isfile(txlog_file)
    if not is_log_file:
        try:
            open(txlog_file, 'x')
            with open(txlog_file, 'a') as txlog_header:
                txlog_header.write('UTxO_Hash,' + 'FromAddr,' + 'Amount,' + 'TAmount,' + 'Token,' + 'Time\n')
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

    rawUtxoTable = subp_proc(tx_list, log)

    # Output rows
    try:
        utxoTableRows = rawUtxoTable.strip().splitlines()
    except AttributeError:
        return

    # Foreach row compare against each line of tx file
    for x in range(2, len(utxoTableRows)):
        if txa_is:
            txarchive_r = open(tx_archive_file, 'r')
        txlog_r = open(txlog_file, 'r')
        cells = utxoTableRows[x].split()
        tk_amt = '0'
        tx_hash = cells[0].decode('utf-8')
        tx_amnt = cells[2].decode('utf-8')
        flag = 0
        aindex = 1
        index = 1
        # Foreach line of the file compare against both tx logs
        if txa_is:
            for txarchiveline in txarchive_r:
                aindex += 1
                if tx_hash in txarchiveline and tx_amnt in txarchiveline:
                    flag = 1
                    txarchive_r.close()
                    break
        for line in txlog_r:
            index += 1
            if tx_hash in line and tx_amnt in line:
                flag = 1
                txlog_r.close()
                break
        if flag == 1:
            continue
        if flag == 0:
            # Get curl data from blockfrost on new tx's only
            headers = {'project_id': api_id}
            cmd = api_uri + 'txs/' + tx_hash + '/utxos'
            tx_result = requests.get(cmd, headers=headers)
                
            # Check if hash found at api
            if 'status_code' in tx_result.json():
                status_code = tx_result.json()['status_code']
                continue
            for tx_data in tx_result.json()['inputs']:
                from_addr = tx_data['address']
            for output in tx_result.json()['outputs']:
                txwrite = [tx_hash, from_addr, '0', '0', 'none', 'time']
                if output['address'] == wallet_addr:
                    for amounts in output['amount']:
                        if amounts['unit'] == 'lovelace':
                            txcount += 1
                            txwrite[2] = str(amounts['quantity'])
                        else:
                            if profile_type == 1 and len(fee_token_string) > 1:
                                fee_token = get_token_string_id(fee_token_string)
                                if amounts['unit'] == fee_token:
                                    txwrite[3] = str(amounts['quantity'])
                                    txwrite[4] = amounts['unit']
                    txlog_a = open(txlog_file, 'a')
                    # Delay to keep timestamps unique
                    sleep(2)
                    txwrite[5] = strftime("%Y-%m-%d_%H-%M-%S", gmtime())
                    txlog_a.write(','.join(txwrite) + '\n')
                    txlog_a.close()
            txlog_r.close()
    return txcount

def process_tally(default_settings, address = 'none', amount = 0):
    # Defaults settings
    log = default_settings[5]

    payments_file = log + 'payments.log'
    final_file = log + 'final.log'

    # If address passed, return tally amount
    if address != 'none':
        # Find all tx from address and get tally
        with open(payments_file, 'r') as pay_r:
            readtx_index = 0
            last_tally = 0
            tally = amount
            
            # Iterate over file lines
            for line in pay_r:
                if readtx_index == 0:
                    readtx_index += 1
                    continue
                readtx_index += 1
                el = line.split(',')
                tx_hash = el[0]
                tx_addr = el[1]
                tx_amnt = int(el[2])
                tk_amnt = int(el[3])
                tk_name = el[4]
                tx_stat = el[5]
                tx_time = el[6]
                tx_tally = int(el[7])

                # Check for matching long addresses
                check_addr = address
                check_tx_addr = tx_addr
                if len(address) == 103:
                    check_addr = address[52:-6]
                    if len(tx_addr) != 103:
                        continue
                    else:
                        check_tx_addr = tx_addr[52:-6]
            
                # Tally matches
                if check_addr == check_tx_addr:
                    last_tally = tx_tally
        
        # Add last matching line tally to current amount and return for checking and possible payments log
        tally += last_tally
        pay_r.close()
        return tally
    else:
        # Find highest addr/tally combo
        cflag = 0
        tally_list = []
        with open(payments_file, 'r') as pay_r:
            readtx_index = 0
            h_tally = 0

            # Iterate over file lines
            for line in pay_r:
                if readtx_index == 0:
                    readtx_index += 1
                    continue
                readtx_index += 1
                el = line.split(',')
                tx_hash = el[0]
                tx_addr = el[1]
                tx_amnt = int(el[2])
                tk_amnt = int(el[3])
                tk_name = el[4]
                tx_stat = el[5]
                tx_time = el[6]
                tx_tally = int(el[7])
                if len(tx_addr) == 103:
                    chck_tx_addr = tx_addr[52:-6]
                
                # check if already logged this address totals
                with open(final_file, 'r') as final_r:
                    readfinal_i = 0
                    for finalr in final_r:
                        if readfinal_i == 0:
                            readfinal_i += 1
                            continue
                        readfinal_i += 1
                        if chck_tx_addr in finalr:
                            cflag = 1
                final_r.close()
                if cflag == 1:
                    continue
                
                # Continue to tally up this address
                final_tally = 0
                readpayi = 0
                for payment in pay_r:
                    if readpayi == 0:
                        readpayi += 1
                        continue
                    readpayi +=1
                    elmod = payment.split(',')
                    el_addr = elmod[1]
                    el_tally = int(elmod[6])
                    chck_addr = el_addr
                    chck_h_addr = tx_addr
                    if len(chck_h_addr) == 103:
                        chck_addr = el_addr[52:-6]
                        chck_h_addr = tx_addr[52:-6]
                    if chck_addr == chck_h_addr:
                        final_tally = el_tally
                tally_list += [[tx_addr, str(final_tally), 'refund']]
        pay_r.close()

        # Record data to final log
        with open(final_file, 'a') as final_a:
            highest = max(tally_list)
            tally_list.remove(highest)
            h_addr = highest[0]
            h_tally = highest[1]
            highest[2] = 'won'
            for tally in tally_list:
                final_a.write(','.join(tally))
            final_a.write(','.join(highest))
            final_a.close()
        return h_addr, h_tally

def check_for_payment(default_settings, custom_settings):
    """
    Checks for an expected amount of ADA from any address in a whitelist (or specific passed) and maintains a log of expected and any other present UTxO payments in profile-specific payments.log file
    """
    # Defaults settings
    log = default_settings[5]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    amount = custom_settings[3]
    min_watch = custom_settings[4]
    sender_addr = custom_settings[5]
    auction = custom_settings[6]
    sc_addr = custom_settings[7]

    # Begin log file
    runlog_file = log + 'run.log'

    # Setup file
    amount = int(amount)
    min_watch = int(min_watch)
    compare_addr = True
    compare_amnt = True
    record_as_payment = ''
    tally_amnt = 0
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
            log_new_txs(default_settings, [api_uri, api_id, watch_addr, fee_token_string])
        except OSError:
            pass

    if not is_paymentlog_file:
        try:
            open(payments_file, 'x')
            with open(payments_file, 'a') as payments_header:
                payments_header.write('UTxO_Hash,' + 'FromAddr,' + 'Amount,' + 'Token Amnt,' + 'Token Name,' + 'Matching,' + 'Time,' + 'Tally\n')
                payments_header.close()
        except OSError:
            pass
    
    # Foreach tx_log row compare against each line of payments_log
    txlog_r = open(txlog_file, 'r')
    with open(txlog_file, 'r') as txlog_r:
        print('\nBeginning loop next')
        readtx_index = 0
        for x in txlog_r:
            if readtx_index == 0:
                readtx_index += 1
                print('\nTitle, skipping')
                continue
            readtx_index += 1
            cells = x.split(',')
            tx_hash = cells[0]
            tx_addr = cells[1]
            tx_amnt = int(cells[2])
            tk_amnt = int(cells[3])
            tk_name = cells[4]
            tx_time = cells[5].strip()
            flag = 0
            readpay_index = 0
            payments_r = open(payments_file, 'r')
            print('\nGot one: '+tx_hash)

            # Foreach line of the file
            for line in payments_r:
                if readpay_index == 0:
                    readpay_index += 1
                    continue
                readpay_index += 1
                if tx_hash in line and str(tx_amnt) in line and tx_time in line:
                    flag = 1
                    break
            if tx_addr == watch_addr or tx_addr == sc_addr:
                # Archive internal TX
                archive_tx(default_settings, [tx_hash, tx_amnt, tx_time])
                flag = 1
            if flag == 1:
                continue
            if flag == 0:
                print('\nnon-self payment...')
                # Get clear representation of address
                if len(sender_addr) == 103:
                    sender_addr_compare = sender_addr[52:-6]
                    tx_addr_compare = tx_addr[52:-6]
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\n--- Long Address Detected, Trimming as: ---\n' + sender_addr_compare + ' | ' + tx_addr_compare + '\n-----------------------------------\n')
                        runlog.close()

                # Compare addresses
                if compare_addr:
                    if tx_addr_compare == sender_addr_compare:
                        print('\nAddresses match')
                        record_as_payment = True
                    else:
                        print('\nAddresses do NOT match')
                        record_as_payment = False
                else:
                    print('\nDo NOT compare addresses')
                    record_as_payment = True

                # Compare values
                if record_as_payment:
                    print('\nRecord_As_Payment Set to True by previous')
                    tally_amnt = process_tally(default_settings, tx_addr, tx_amnt)
                    print('\nGot tally:'+str(tally_amnt))
                    if compare_amnt:
                        print('\nCompare amounts is true: min_watch or exact is above 0')
                        if min_watch > 0 and tally_amnt >= min_watch:
                            print('\nMin_watch is above 0 and tally_amnt is >= min_watch, set payment to true')
                            record_as_payment = True
                        elif tally_amnt == amount:
                            print('\ntally_amnt == amount (expected amnt), set to true')
                            record_as_payment = True
                        else:
                            print('\nNo amount matching, set to false')
                            record_as_payment = False

                # Set status based on record payment value
                if record_as_payment == True:
                    record_as_payment = False
                    txlog_r.close()
                    payments_r.close()
                    return tx_hash + ',' + tx_addr + ',' + str(tx_amnt) + ',' + str(tk_amnt) + ',' + tk_name + ',1,' + tx_time + ',' + str(tally_amnt)
                if record_as_payment == False:
                    return tx_hash + ',' + tx_addr + ',' + str(tx_amnt) + ',' + str(tk_amnt) + ',' + tk_name + ',0,' + tx_time + ',' + str(tally_amnt)
            payments_r.close()
    txlog_r.close()
    return ',,0,0,,2,0,0'

def clean_folder(default_settings):
    # Defaults settings
    cache = default_settings[6]

    from os import remove
    from glob import glob
    files = glob(cache + '*')
    for f in files:
        remove(f)

def proto(default_settings):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    cache = default_settings[6]
    testnet = default_settings[8]

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

def get_utxo(default_settings, token_wallet, file_name):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    cache = default_settings[6]
    testnet = default_settings[8]

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

def get_txin(default_settings, file_name, collateral = 2000000, spendable = False, allowed_datum = '', check_amnt = 0):
    # Defaults settings
    log = default_settings[5]
    cache = default_settings[6]

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

def get_tip(default_settings, add_slots = 1000, target_slot = 0):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    cache = default_settings[6]
    testnet = default_settings[8]

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
    latest_tip = int(td['slot'])
    block = int(td['block'])
    if target_slot > 0:
        return latest_tip, target_slot, block
    else:
        return latest_tip, latest_tip + add_slots, block

def calc_fee(default_settings, counts):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    log = default_settings[5]
    cache = default_settings[6]
    testnet = default_settings[8]

    # Begin log file
    runlog_file = log + 'run.log'
    fee = [
        cardano_cli,
        'transaction',
        'calculate-min-fee',
        '--tx-body-file',
        cache+'tx.tmp',
        '--tx-in-count',
        str(counts[0]),
        '--tx-out-count',
        str(counts[1]),
        '--witness-count',
        str(counts[2]),
        '--' + network,
        '--protocol-params-file',
        cache + 'protocol.json'
    ]
    if testnet:
        fee.insert(12, magic)    
    p = subprocess.Popen(fee, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
    s = str(p).strip()
    f = ''.join(filter(str.isdigit, s))
    return f

def build_raw_tx(default_settings, counts, until_tip, utxo_in, utxo_col, utxo_out, tx_data, manual = False, fee = 0):
    # Defaults settings
    profile_name = default_settings[0]
    cardano_cli = default_settings[2]
    log = default_settings[5]
    cache = default_settings[6]

    # Begin log file
    runlog_file = log + 'run.log'

    if fee == 0:
        # Do raw build for fee calculation
        pre = [
            cardano_cli,
            'transaction',
            'build-raw',
            '--alonzo-era',
            '--fee',
            '0',
            '--invalid-hereafter',
            str(until_tip),
            '--out-file',
            cache+'tx.tmp'
        ]
        pre += utxo_in
        pre += utxo_col
        pre += utxo_out
        pre += tx_data
        p = subprocess.Popen(pre)
        p.communicate()

        # Return calculated fee
        get_fee = calc_fee(profile_name, counts)
        return int(get_fee)

    # Run build with calculated fee
    fee = str(fee)
    func = [
        cardano_cli,
        'transaction',
        'build-raw',
        '--alonzo-era',
        '--fee',
        fee,
        '--invalid-hereafter',
        str(until_tip),
        '--out-file',
        cache+'tx.draft'
    ]
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

def build_tx(default_settings, change_addr, until_tip, utxo_in, utxo_col, utxo_out, tx_data, manual = False):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    log = default_settings[5]
    cache = default_settings[6]
    testnet = default_settings[8]

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

def sign_tx(default_settings, custom_settings):
    # Default settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    log = default_settings[5]
    cache = default_settings[6]
    txlog = default_settings[7]
    testnet = default_settings[8]

    # Custom settings
    witnesses = custom_settings[0]
    filePre = custom_settings[1]

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

def submit_tx(default_settings, custom_settings):
    # Defaults settings
    cardano_cli = default_settings[2]
    network = default_settings[3]
    magic = default_settings[4]
    log = default_settings[5]
    txlog = default_settings[7]
    testnet = default_settings[8]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]

    # Settings list to pass to log_new_txs and archive_tx
    log_settings = [api_uri, api_id, watch_addr, fee_token_string]

    if tx_hash_in != 'mint':
        # Get latest transactions first
        log_new_txs(default_settings, log_settings)

    # Archive TX
    if tx_hash_in != 'none' and tx_hash_in != 'mint':
        archive_tx(default_settings, [tx_hash_in, tx_amnt_in, tx_time])
        
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

    if tx_hash_in != 'mint':
        # Get latest transactions after, loop check TX hash and log new txs
        log_new_txs(default_settings, log_settings)

    # Get Hash
    tx_hash = get_tx_hash(default_settings, filePre)
    tx_hash = tx_hash.strip()

    if tx_hash_in != 'mint':        
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nWaiting for ' + filePre + 'tx to clear, with hash: ' + tx_hash)
            runlog.close()
        tx_hash_flag = False
        while not tx_hash_flag:
            sleep(2)
            log_new_txs(default_settings, log_settings)
            tx_hash_flag = check_for_tx(default_settings, tx_hash)
    # Archive self tx (speeds up processing)
    if tx_hash_in != 'none' and tx_hash_in != 'mint':
        archive_tx(default_settings, [tx_hash, 0, 'none'])
    return tx_hash