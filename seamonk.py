import os
import readline
import subprocess
import json
import cardanotx as tx
import getopt
import shutil
import time
from sys import exit, argv
from os.path import isdir, isfile
from time import sleep, strftime, gmtime

def inputp(prompt, text):
    def hook():
        readline.insert_text(text)
        readline.redisplay()
    readline.set_pre_input_hook(hook)
    result = input(prompt)
    readline.set_pre_input_hook()
    return result
    
def deposit(default_settings, custom_settings):
    # Default settings
    log = default_settings[5]
    cache = default_settings[6]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]
    watch_skey_path = custom_settings[8]
    smartcontract_addr = custom_settings[9]
    smartcontract_path = custom_settings[10]
    token_policy_id = custom_settings[11]
    token_name = custom_settings[12]
    deposit_amt = custom_settings[13]
    sc_ada_amt = custom_settings[14]
    ada_amt = custom_settings[15]
    datum_hash = custom_settings[16]
    check_price = custom_settings[17]
    collateral = custom_settings[18]
    tokens_to_swap = custom_settings[19]
    recipient_addr = custom_settings[20]
    replenish = custom_settings[21]

    submit_settings = [api_uri, api_id, watch_addr, fee_token_string, filePre, tx_hash_in, tx_amnt_in, tx_time]

    # Begin log file and clear cache 
    runlog_file = log + 'run.log'
    tx.clean_folder(default_settings)
    tx.proto(default_settings)
    tx.get_utxo(default_settings, watch_addr, 'utxo.json')
    
    # Get wallet utxos
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(default_settings, 'utxo.json', collateral)

    # Check for price amount + other needed amounts in watched wallet
    if check_price > 0:
        price = check_price
        fee_buffer = 1000000
        check_price = int(check_price) + int(sc_ada_amt) + int(ada_amt) + int(collateral) + fee_buffer
        if not replenish:
            print('\nCheck Price now: ', check_price)
        is_price_utxo = tx.get_txin(default_settings, 'utxo.json', collateral, False, '', int(check_price))
        if not is_price_utxo:
            if not replenish:
                print("\nNot enough ADA in your wallet to cover Price and Collateral. Add some funds and try again.\n")
                exit(0)

    if not flag: # TODO: Test with different tokens at bridge wallet
        filePreCollat = 'collatRefill_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
        if not replenish:
            print("No collateral UTxO found! Attempting to create...")
        _, until_tip, block = tx.get_tip(default_settings)
        # Setup UTxOs
        tx_out = tx.process_tokens(default_settings, tokens, watch_addr, ['all'], ada_amt) # Process all tokens and change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Create collateral UTxO
        if not replenish:
            print('\nTX Out Settings for Creating Collateral: ', tx_out)
        tx_data = [
            ''
        ]
        tx.build_tx(default_settings, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        # Sign and submit the transaction
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(default_settings, [witnesses, filePreCollat])
        if not replenish:
            print('\nSubmitting and waiting for new UTxO to appear on blockchain...')
        tx_hash_collat = tx.submit_tx(default_settings, submit_settings)
        if not replenish:
            print('\nTX Hash returned: ' + tx_hash_collat)
    
    # Build, sign, and send transaction
    if flag is True:
        _, until_tip, block = tx.get_tip(default_settings)
        
        # Calculate token quantity and any change
        tok_bal = 0
        sc_out = int(deposit_amt)
        tok_new = 0
        for token in tokens:
            if token == 'lovelace':
                continue
            for t_qty in tokens[token]:
                tok_bal = tokens[token][t_qty]
                tok_new = tok_bal - sc_out - tokens_to_swap
        if tok_new < 0:
            return 'Error: Token Balance in Watched Wallet Too Low For Replenish+Swap'

        # Setup UTxOs
        tx_out = tx.process_tokens(default_settings, tokens, watch_addr, ['all'], ada_amt, [token_policy_id, token_name]) # Account for all except token to swap
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # UTxO to replenish collateral
        if tok_new > 0:
            tx_out += tx.process_tokens(default_settings, tokens, watch_addr, [tok_new], ada_amt) # Account for deposited-token change (if any)
        if tokens_to_swap > 0:
            tx_out += tx.process_tokens(default_settings, tokens, recipient_addr, [tokens_to_swap], ada_amt, [token_policy_id, token_name], False) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(default_settings, tokens, smartcontract_addr, [sc_out], sc_ada_amt, [token_policy_id, token_name], False) # Send just the token for swap
        tx_out += '--tx-out-datum-hash', datum_hash
        tx_data = []
        if replenish:
            if sc_out > tok_bal:
                sc_out = tok_bal
            tx.get_utxo(default_settings, smartcontract_addr, 'utxo_script.json')
            if isfile(cache+'utxo_script.json') is False:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nERROR: Could not file utxo_script.json\n')
                    runlog.close()
                return False
            _, _, sc_tokens, _, data_list = tx.get_txin(default_settings, 'utxo_script.json', collateral, True, datum_hash)

            sc_out_tk = 0
            for token in sc_tokens:
                # lovelace will be auto accounted for using --change-address
                if token == 'lovelace':
                    continue
                for t_qty in sc_tokens[token]:
                    sc_out_tk = [sc_tokens[token][t_qty]]

            for key in data_list:
                # A single UTXO with a single datum can be spent
                if data_list[key] == datum_hash:
                    utxo_in += ['--tx-in', key]
                    break
            tx_out += ['--tx-out', watch_addr + '+' + str(price)] # UTxO for price
            tx_out += tx.process_tokens(default_settings, sc_tokens, watch_addr, sc_out_tk, sc_ada_amt) # UTxO to Get SC Tokens Out
            tx_data = [
                '--tx-out-datum-hash', datum_hash,
                '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
                '--tx-in-redeemer-value', '""',
                '--tx-in-script-file', smartcontract_path
            ]

        tx.build_tx(default_settings, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        # Sign and submit the transaction
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(default_settings, [witnesses, filePre])
        tx_hash = tx.submit_tx(default_settings, submit_settings)
    else:
        if not replenish:
            print('\nCollateral UTxO missing or couldn\'t be created! Exiting...\n')
            exit(0)
        tx_hash = 'error'
    return tx_hash

def withdraw(default_settings, custom_settings):
    # Defaults settings
    log = default_settings[5]
    cache = default_settings[6]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]
    watch_skey_path = custom_settings[8]
    smartcontract_addr = custom_settings[9]
    smartcontract_path = custom_settings[10]
    token_policy_id = custom_settings[11]
    token_name = custom_settings[12]
    datum_hash = custom_settings[13]
    recipient_addr = custom_settings[14]
    return_ada = custom_settings[15]
    price = custom_settings[16]
    collateral = custom_settings[17]
    refund_amnt = custom_settings[18]
    refund_type = custom_settings[19]
    magic_price = custom_settings[20]

    submit_settings = [api_uri, api_id, watch_addr, fee_token_string, filePre, tx_hash_in, tx_amnt_in, tx_time]


    # Begin log file
    runlog_file = log + 'run.log'

    # Clear the cache
    tx.clean_folder(default_settings)
    tx.proto(default_settings)
    tx.get_utxo(default_settings, watch_addr, 'utxo.json')

    # Run get_txin
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(default_settings, 'utxo.json', collateral)
    flag = True
    # Build, Sign, and Send TX
    if flag is True or collateral == 1:
        _, until_tip, block = tx.get_tip(default_settings)
        
        token_amnt = ['all']
        if refund_amnt > 0:
            refund_string = recipient_addr + '+' + str(refund_amnt)
            # Check for refund type: 0 = just a simple refund; 1 = include 40 JUDE & any clue; 2 = include any clue
            ct = 0
            
            if refund_type == 1:
                ct = 40
                # Calculate any clue
                if magic_price == 0:
                    ct = 41
                else:
                    clue_diff = int(refund_amnt) / int(magic_price)
                    if clue_diff >= 0.8:
                        ct = 130
                    if clue_diff <= 0.2:
                        ct = 50
                clue_token = str(ct)
                refund_string += '+' + clue_token + ' ' + token_policy_id + '.' + token_name
            if refund_type == 2:
                # Calculate any clue
                if magic_price == 0:
                    ct = 1
                else:
                    clue_diff = int(refund_amnt) / int(magic_price)
                    if clue_diff >= 0.8:
                        ct = 90
                    if clue_diff <= 0.2:
                        ct = 10
                clue_token = str(ct)
                refund_string += '+' + clue_token + ' ' + token_policy_id + '.' + token_name
            if refund_type == 3:
                ct = 40
                if magic_price == 0:
                    ct = 41
                clue_token = str(ct)
                refund_string += '+' + clue_token + ' ' + token_policy_id + '.' + token_name
            if refund_type == 4:
                if magic_price == 0:
                    ct = 1
                clue_token = str(ct)
                refund_string += '+' + clue_token + ' ' + token_policy_id + '.' + token_name

            if ct > 0:
                token_amnt = ['except', ct]
            tx_out_refund = ['--tx-out', refund_string] # UTxO to Refund
        tx_out = tx.process_tokens(default_settings, tokens, watch_addr, token_amnt) # Change
        if collateral != 1:
            tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if tx_out_refund:
            tx_out += tx_out_refund # The final refund out if any
        tx_data = []
        if refund_amnt == 0:
            tx.get_utxo(default_settings, smartcontract_addr, 'utxo_script.json')
            if isfile(cache+'utxo_script.json') is False:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nERROR: Could not file utxo_script.json\n')
                    runlog.close()
                return False
            _, _, sc_tokens, _, data_list = tx.get_txin(default_settings, 'utxo_script.json', collateral, True, datum_hash)

            sc_out = 0
            for token in sc_tokens:
                # lovelace will be auto accounted for using --change-address
                if token == 'lovelace':
                    continue
                for t_qty in sc_tokens[token]:
                    sc_out = [sc_tokens[token][t_qty]]
            for key in data_list:
                # A single UTXO with a single datum can be spent
                if data_list[key] == datum_hash:
                    utxo_in += ['--tx-in', key]
                    break
            tx_out += ['--tx-out', watch_addr + '+' + str(price)] # UTxO for price if set to process price payment
            tx_out += tx.process_tokens(default_settings, sc_tokens, watch_addr, sc_out, return_ada) # UTxO to Get SC Tokens Out
            tx_data = [
                '--tx-out-datum-hash', datum_hash,
                '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
                '--tx-in-redeemer-value', '""',
                '--tx-in-script-file', smartcontract_path
            ]
        tx.build_tx(default_settings, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(default_settings, [witnesses, filePre])
        tx_hash = tx.submit_tx(default_settings, submit_settings)
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nNo collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.\n')
            runlog.close()
        tx_hash = 'error'
    return tx_hash

def smartcontractswap(default_settings, custom_settings):
    # Defaults settings
    log = default_settings[5]
    cache = default_settings[6]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]
    watch_skey_path = custom_settings[8]
    smartcontract_addr = custom_settings[9]
    smartcontract_path = custom_settings[10]
    token_policy_id = custom_settings[11]
    token_name = custom_settings[12]
    datum_hash = custom_settings[13]
    recipient_addr = custom_settings[14]
    return_ada = custom_settings[15]
    price = custom_settings[16]
    collateral = custom_settings[17]
    token_qty = custom_settings[18]

    submit_settings = [api_uri, api_id, watch_addr, fee_token_string, filePre, tx_hash_in, tx_amnt_in, tx_time]

    # Begin log file
    runlog_file = log + 'run.log'

    # Clear the cache
    tx.clean_folder(default_settings)
    tx.proto(default_settings)
    tx.get_utxo(default_settings, watch_addr, 'utxo.json')
    
    # Run get_txin
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(default_settings, 'utxo.json', collateral)
    
    # Build, Sign, and Send TX
    if flag is True:
        tx.get_utxo(default_settings, smartcontract_addr, 'utxo_script.json')
        if isfile(cache+'utxo_script.json') is False:
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nERROR: Could not file utxo_script.json\n')
                runlog.close()
            return False
        _, _, sc_tokens, _, data_list = tx.get_txin(default_settings, 'utxo_script.json', collateral, True, datum_hash)
        contract_utxo_in = utxo_in
        for key in data_list:
            # A single UTXO with a single datum can be spent
            if data_list[key] == datum_hash:
                contract_utxo_in += ['--tx-in', key]
                break
        _, until_tip, block = tx.get_tip(default_settings)
        # Calculate token quantity and change
        sc_bal = 0
        sc_out = int(token_qty)
        sc_new = 0
        for token in sc_tokens:
            # lovelace will be auto accounted for using --change-address
            if token == 'lovelace':
                continue
            for t_qty in sc_tokens[token]:
                sc_bal = sc_tokens[token][t_qty]
                sc_new = sc_bal - sc_out
        tx_out = tx.process_tokens(default_settings, sc_tokens, recipient_addr, [sc_out], return_ada) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(default_settings, tokens, watch_addr) # Change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if price:
            tx_out += ['--tx-out', watch_addr + '+' + str(price)] # UTxO for price if set to process price payment
        if sc_new > 0:
            tx_out += tx.process_tokens(default_settings, sc_tokens, smartcontract_addr, [sc_new]) # UTxO to Send Change to Script - MUST BE LAST UTXO FOR DATUM
        tx_data = [
            '--tx-out-datum-hash', datum_hash,
            '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
            '--tx-in-redeemer-value', '""',
            '--tx-in-script-file', smartcontract_path
        ]
        tx.build_tx(default_settings, watch_addr, until_tip, contract_utxo_in, utxo_col, tx_out, tx_data)
        
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(default_settings, [witnesses, filePre])
        tx_hash = tx.submit_tx(default_settings, submit_settings)
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nNo collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.\n')
            runlog.close()
        tx_hash = 'error'
    return tx_hash

def mint(default_settings, custom_settings):
    # Defaults settings
    log = default_settings[5]
    cache = default_settings[6]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]
    return_ada = custom_settings[8]
    src = custom_settings[9]
    mint_addr = custom_settings[10]
    wallet_skey_path = custom_settings[11]
    policy_skey_path = custom_settings[12]
    nft_addr = custom_settings[13]
    nft_data = custom_settings[14]
    manual = custom_settings[15]                                      #= False


    submit_settings = [api_uri, api_id, watch_addr, fee_token_string, filePre, tx_hash_in, tx_amnt_in, tx_time]

    # Assign vars from list
    nft_name = nft_data[0]
    nft_qty = nft_data[1]
    nft_json = nft_data[2]
    nft_lock = int(nft_data[3])
    nft_add = int(nft_data[4])
    nft_policy = nft_data[5]

    # Begin log file
    runlog_file = log + 'run.log'

    # Clear the cache
    tx.clean_folder(default_settings)
    tx.proto(default_settings)
    tx.get_utxo(default_settings, mint_addr, 'utxo.json')

    # Get locking tip
    if nft_add < 900 and nft_lock == 0:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nLocking tip is probably too soon, trying anyway...')
            runlog.close()
        if manual:
            print('\nLocking tip is too soon! To ensure minting completes in time, please try again with a tip of 900 (15 min) or higher')
            exit(0)
    if nft_lock > 0:
        until_tip = nft_lock
        latest_tip, _, _ = tx.get_tip(default_settings, 0, until_tip)
        tip_diff = until_tip - latest_tip
        if tip_diff < 600 and tip_diff > 120:
            if manual:
                print('\nTarget locking height is only 2 ~ 10 min in the future, try to continue anyway?')
                try_continue = input('Yes or No:')
                if try_continue == 'No' or try_continue == 'no':
                    print('\nExiting...')
                    exit(0)
            else:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nTarget locking height is only 2 ~ 10 min in the future, trying anyway...')
                    runlog.close()
        if tip_diff < 120:
            if manual:
                print('\nTarget locking height is in less than 2 min and will likely fail, try anyway?')
                try_continue = input('Yes or No:')
                if try_continue == 'No' or try_continue == 'no':
                    print('\nExiting...')
                    exit(0)
            else:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nTarget locking height is less than 2 min in the future, trying anyway...')
                    runlog.close()
    else:
        _, until_tip, _ = tx.get_tip(default_settings, nft_add)

    # Setup NFT files
    template_script = src + 'template.script'
    out_script = log + nft_name + '.script'
    nft_json_out = log + nft_name + '.json'
    out_id = log + nft_name + '.id'

    # Save policy file
    with open(template_script, 'r') as script:
        scriptData = script.read()
        script.close()
    scriptData = scriptData.replace('0fff0', ' '.join(nft_policy.split()))
    scriptData = scriptData.replace('1111', ' '.join(str(until_tip).split()))
    with open(out_script, 'w') as scriptout:
        scriptout.write(scriptData)
        scriptout.close()

    # Generate and output Policy ID
    nft_id = tx.get_token_id(default_settings, out_script)
    with open(out_id, 'w') as outid:
        outid.write(nft_id)
        outid.close()
    nft_asset = nft_id + '.' + nft_name
    
    # Modify and save JSON file
    with open(nft_json, 'r') as jsonsrc:
        jsonData = jsonsrc.read()
        jsonsrc.close()
    jsonData = jsonData.replace('000_POLICY_ID_000', ' '.join(nft_id.split()))
    if not manual:
        html_in = log + nft_name + '-temp.html'
        html_out = log + nft_name + '.html'
        with open(html_in, 'r') as htmlsrc:
            htmlData = htmlsrc.read()
            htmlsrc.close()
        firstpart = nft_addr[0:16]
        lastpart = nft_addr[-16:]
        s_addr = firstpart + ' . . . ' + lastpart
        htmlData = htmlData.replace('__00_ADDRL_00__', ' '.join(nft_addr.split()))
        htmlData = htmlData.replace('__00_ADDR_00__', ' '.join(s_addr.split()))
        with open(html_out, 'w') as htmlout:
            htmlout.write(htmlData)
            htmlout.close()
        html_json = json.dumps(tx.encode_to_base64(html_out, 'html'))
        jsonData = jsonData.replace('000_FILE_000', ' '.join(html_json.split()))
    with open(nft_json_out, 'w') as jsonout:
        jsonout.write(jsonData)
        jsonout.close()
    
    # Run get_txin
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(default_settings, 'utxo.json')
    
    # Build Raw Temp
    tx_out_own = tx.process_tokens(default_settings, tokens, mint_addr, ['all'], return_ada, '', True, True, return_ada) # ADA Calc Change
    tx_out_nft = ['--tx-out', nft_addr + '+' + return_ada + '+' + nft_qty + ' ' + nft_asset] # Send NFT to winner

    tx_out_temp = tx_out_own
    tx_out_temp += tx_out_nft
    tx_data = [
        '--mint=' + nft_qty + ' ' + nft_asset,
        '--minting-script-file', out_script,
        '--metadata-json-file', nft_json_out
    ]
    witnesses = [
        '--signing-key-file',
        wallet_skey_path,
        '--signing-key-file',
        policy_skey_path
    ]
    utxo_in_count = len(utxo_in) // 2
    utxo_out_count = len(tx_out_temp)
    witness_count = len(witnesses) // 2
    counts = [utxo_in_count, utxo_out_count, witness_count]

    # Get fee and recalculate UTxOs
    fee = tx.build_raw_tx(default_settings, counts, until_tip, utxo_in, utxo_col, tx_out_temp, tx_data, manual)
    reserve_ada = int(return_ada) + int(fee)
    tx_out_own_new = tx.process_tokens(default_settings, tokens, mint_addr, ['all'], return_ada, '', True, True, reserve_ada) # ADA Calc Change
    tx_out = tx_out_own_new
    tx_out += tx_out_nft

    # Build new tx with fees
    tx.build_raw_tx(default_settings, counts, until_tip, utxo_in, utxo_col, tx_out, tx_data, manual, fee)
    
    # Sign and send
    tx.sign_tx(default_settings, [witnesses, filePre])
    tx_hash = tx.submit_tx(default_settings, submit_settings)
    if manual:
        return tx_hash, nft_id, str(until_tip)
    return tx_hash

def start_deposit(default_settings, custom_settings):
    # Default settings
    log = default_settings[5]
    cache = default_settings[6]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]
    watch_skey_path = custom_settings[8]
    watch_vkey_path = custom_settings[9]
    watch_key_hash = custom_settings[10]
    smartcontract_path = custom_settings[11]
    token_policy_id = custom_settings[12]
    token_name = custom_settings[13]
    check_price = custom_settings[14]
    collateral = custom_settings[15]

    # Begin log file
    runlog_file = log + 'run.log'

    smartcontract_addr = tx.get_smartcontract_addr(default_settings, smartcontract_path)

    print("\n--- NOTE: Proceed Only If You Are Depositing Your NFT or Tokens Into the NFT/Token Swap Smart Contract ---\n")
    print("\n---       Be sure you have at least 1 UTxO in your wallet with 2 ADA for collateral before running this.   ---\n")
    print("\n-----------------------------\n| Please Verify Your Input! |\n-----------------------------\n")
    print("\nMy Watched Wallet Address >> ",watch_addr)
    print("\nMy Address PubKey Hash (for smartcontract validation) >> ",str(watch_key_hash))
    print("\nMy Watched Addresses skey File Path >> ",watch_skey_path)
    print("\nSmartContract Address >> ",smartcontract_addr)
    print("\nNative Token Policy ID >> ",token_policy_id)
    print("\nNative Token Name >> ",token_name)
    
    
    verify = input("\n\nIs the information above correct AND you have a 2 ADA UTxO for Collateral? (yes or no): ")
    
    if verify == ("yes"):
        print("\n\nContinuing . . . \n")
    elif verify == ("no"):
        print("\n\nQuitting, please run again to try again!\n\n")
        exit(0)
    
    deposit_amt = input("\nHow many " + token_name + " tokens are you depositing?\nDeposit Amount:")
    sc_ada_amt = input("\nHow many lovelace to include with token(s) at SmartContract UTxO? (must be at least protocol minimum for token(s))\nLovelace Amount SmartContract:")
    ada_amt = input("\nHow many lovelace to include with token(s) at watched address UTxO(s)? (must be at least protocol minimum for token(s))\nLovelace Amount Wallet:")

    unique_id = tx.get_token_identifier(token_policy_id, token_name)
    datum_hash  = tx.get_hash_value(default_settings, '"{}"'.format(unique_id)).replace('\n', '')
    filePre = 'depositSC_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
    deposit_settings = [api_uri, api_id, watch_addr, fee_token_string, filePre, tx_hash_in, tx_amnt_in, tx_time, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, deposit_amt, sc_ada_amt, ada_amt, datum_hash, check_price, collateral, 0, '', False]
    tx_hash = deposit(default_settings, deposit_settings)
    print('\nDeposit is processing . . . ')
    tx.log_new_txs(default_settings, [api_uri, api_id, watch_addr, ''])
    sleep(2)
    if tx_hash != 'error':
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nDeposit hash found, TX completed.')
            runlog.close()
        print('\nDeposit Completed!')
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nTX attempted, error returned by deposit attempt')
            runlog.close()
        print('\nDeposit Failed!')

def create_smartcontract(default_settings, custom_settings):
    # Default settings
    log = default_settings[5]
    cache = default_settings[6]

    # Custom settings
    api_uri = custom_settings[0]
    api_id = custom_settings[1]
    watch_addr = custom_settings[2]
    fee_token_string = custom_settings[3]
    filePre = custom_settings[4]
    tx_hash_in = custom_settings[5]
    tx_amnt_in = custom_settings[6]
    tx_time = custom_settings[7]
    approot = custom_settings[8]
    sc_path = custom_settings[9]
    src = custom_settings[10]
    pubkeyhash = custom_settings[11]
    price = custom_settings[12]
    
    # Replace the validator options
    template_src = src + 'src/' + 'template_SwapToken.hs'
    output_src = src + 'src/' + 'SwapToken.hs'
    with open(template_src, 'r') as smartcontract :
        scdata = smartcontract.read()
        smartcontract.close()
    scdata = scdata.replace('PUBKEY_HASH010101010101010101010101010101010101010101010', ' '.join(pubkeyhash.split()))
    scdata = scdata.replace('PRICE_00000000000000', ' '.join(price.split()))
    with open(output_src, 'w') as smartcontract:
        smartcontract.write(scdata)
        smartcontract.close()
    
    # Compile the plutus smartcontract
    approot = os.path.realpath(os.path.dirname(__file__))
    os.chdir(src)
    print("\nPlease wait while your SmartContract source is being compiled, this may take a few minutes . . .\n\n")
    sleep(5)
    data_build = subprocess.call(['cabal', 'build'], stdout = subprocess.PIPE)
    print('\nGenerating SmartContract Plutus Script . . .')
    data_run = subprocess.call(['cabal', 'run'], stdout = subprocess.PIPE)
    print("\nCheck the above output for any errors.")

    # Move the plutus file to the working directory
    os.remove(output_src)
    os.replace(src + 'swaptoken.plutus', sc_path)
    SC_ADDR = tx.get_smartcontract_addr(default_settings, sc_path)

    print('\n================ Finished! ================\n > This SmartContract Address For Your Records Is (if testnet it will be different when you go mainnet): ' + SC_ADDR + '\n\n')
    exit(0)

def setup(logroot, profile_name='', reconfig = False, append = False):
    # Default and shared variables
    PROFILE_TYPE, NETWORK_INPUT, MAGIC_INPUT, CLI_PATH_INPUT, API_ID_INPUT, COLLATERAL_INPUT, WLENABLED_INPUT, WHITELIST_ONCE_INPUT, WATCH_SKEY_PATH_INPUT, WATCH_VKEY_PATH_INPUT, SMARTCONTRACT_PATH_INPUT, TOKEN_POLICY_ID_INPUT, TOKEN_NAME_INPUT, EXPECT_ADA_INPUT, MIN_WATCH_INPUT, PRICE_INPUT, TOKEN_QTY_INPUT, RETURN_ADA_INPUT, DEPOSIT_AMNT_INPUT, RECURRINGSTRING_INPUT, SC_ADA_AMNT_INPUT, WT_ADA_AMNT_INPUT, AUTO_REFUND_INPUT, FEE_CHARGE_INPUT, AUCTIONINPUT, MINT_SKEY, MINT_VKEY, MINT_POLICY_SKEY, MINT_POLICY_VKEY, MINT_NFT_NAME, MINT_NFT_QTY, MINT_TARGET_TIP, MINT_LAST_TIP, BLOCKTIMEINPUT, NFT_ADDR = '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''

    # Minting Defaults
    AUCTIONEND = 0
    NFT_MINTED = False

    if reconfig:
        settings_file = 'profile.json'
        # Load settings
        load_profile = json.load(open(settings_file, 'r'))
        if len(profile_name) == 0:
            profile_name = list(load_profile.keys())[0]
        PROFILE = load_profile[profile_name]
        PROFILE_TYPE = int(PROFILE['type'])
        CLI_PATH_INPUT = PROFILE['cli_path']
        API_ID_INPUT = PROFILE['api']
        COLLATERAL_INPUT = PROFILE['collateral']
        TOKEN_POLICY_ID_INPUT = PROFILE['tokenid']
        TOKEN_NAME_INPUT = PROFILE['tokenname']
        EXPECT_ADA_INPUT = PROFILE['expectada']
        MIN_WATCH_INPUT = PROFILE['min_watch']
        WLENABLED_INPUT = PROFILE['wlenabled']
        WHITELIST_ONCE_INPUT = PROFILE['wlone']
        RETURN_ADA_INPUT = PROFILE['returnada']

        if PROFILE_TYPE == 0:
            WATCH_SKEY_PATH_INPUT = PROFILE['watchskey']
            WATCH_VKEY_PATH_INPUT = PROFILE['watchvkey']
            SMARTCONTRACT_PATH_INPUT = PROFILE['scpath']
            PRICE_INPUT = PROFILE['price']
            TOKEN_QTY_INPUT = PROFILE['tokenqty']
            DEPOSIT_AMNT_INPUT = PROFILE['deposit_amnt']
            RECURRINGSTRING_INPUT = PROFILE['recurring']
            SC_ADA_AMNT_INPUT = PROFILE['sc_ada_amnt']
            WT_ADA_AMNT_INPUT = PROFILE['wt_ada_amnt']
            AUTO_REFUND_INPUT = PROFILE['auto_refund']
            FEE_CHARGE_INPUT = PROFILE['fee_to_charge']

        if PROFILE_TYPE == 1:
            NFT_MINTED = PROFILE['nft_minted']
            MINT_SKEY = PROFILE['wallet_skey']
            MINT_VKEY = PROFILE['wallet_vkey']
            MINT_POLICY_SKEY = PROFILE['policy_skey']
            MINT_POLICY_VKEY = PROFILE['policy_vkey']
            NFT_ADDR = PROFILE['nft_addr']
            NFT_DATA = PROFILE['nft_data']
            MINT_NFT_NAME = NFT_DATA[0]
            MINT_NFT_QTY = NFT_DATA[1]
            MINT_NFT_JSON = NFT_DATA[2]
            MINT_TARGET_TIP = NFT_DATA[3]
            MINT_LAST_TIP = NFT_DATA[4]
            AUCTIONINPUT = PROFILE['auction']
            BLOCKTIMEINPUT = PROFILE['blocktime']
        
        UNIQUE_NAME = profile_name
        print('\n!!! WARNING !!!\nSettings for profile "' + profile_name + '" are about to be overwritten!\n\nExit now if you do not want to do that.\n\n')
    
    print('\n========================= Setting Up New Profile =========================\n')
    if not reconfig:
        print('\n    Choose profile type by entering the cooresponding number:')
        print('      0 = SmartContract Swap')
        print('      1 = Blockchain Auction')
        RESPONSE = input('\nEnter the option number:')
        PROFILE_TYPE = int(RESPONSE)
        UNIQUE_NAME = input('\nEnter A Unique Profile Name For This Profile\n(no spaces, e.g. CypherMonk_NFT_Sale)\n >Unique Name:')
    
    print('\n*IMPORTANT NOTES*')
    print('If this is the first time running the setup a profile.json file will be')
    print('created within this working directory. If this is a new profile addition,')
    print('it will be added to the json of the profile.json file and should be called')
    print('with the profile option like so: `python3 seamonk.py --profile MyProfileName`')
    print('where MyProfileName is the name you give this profile.')
    print('\nFor new profiles, this will also generate a whitelist.txt file within the')
    print('profiles directory, under the directory named after this profile,')
    print('e.g. profiles/MyProfileName/whitelist.txt. Please add the Cardano addresses')
    print('you would like whitelisted to this file, each on a new line. Note that only')
    print('1 address from each whitelisted wallet with a complex 103-length address')
    print('need be added and the entire wallet will be whitelisted.\n\n')
    print('Default for all profiles is mainnet, if you want to test a profile first')
    print('you can add the option with various optional values:')
    print('     `--testnet MAGICNUM,APIID,TOKENPOLICY.TOKENNAME,TARGETSLOT`')
    print('where MAGICNUM is the testnet magic number, APIID is your testnet-specific')
    print('Blockfrost API ID, TARGETSLOT is an optional block slot height override,')
    print('and TOKENPOLICY.TOKENNAME is an override for an alt token if you set one.')
    print('\nIf leaving out one of the overrides, such as TARGETSLOT or the token, ')
    print('be sure to still include all the commas in..e.g. `--testnet MAGICNUM,APIID,,')
    print('\n\nFOR BEST RESULTS: All settings should be for mainnet and your folder')
    print('structure and file naming should match that of mainnet, this way you can')
    print('stage with testnet overrides and when all is working, simply copy your')
    print('working profile to your mainnet environment.  The location of SeaMonk')
    print('is dynamic, so only the locations set during this setup are important')
    print('to keep consistent between staging and live.')

    # Setup profile-specific cache and log folders
    log = os.path.join(os.path.join(logroot, UNIQUE_NAME), '')
    cache = os.path.join(os.path.join(log, 'cache'), '')
    txlog = os.path.join(os.path.join(log, 'txs'), '')
    try:
        os.mkdir(log)
    except OSError:
        pass
    try:
        os.mkdir(cache)
    except OSError:
        pass
    try:
        os.mkdir(txlog)
    except OSError:
        pass                

    CLI_PATH = inputp('\nExplicit Path To "cardano-cli"\n(leave empty if cardano-cli is in your system path and\nit is the version you want to use with this profile)\n >Cardano-CLI Path:', CLI_PATH_INPUT)
    API_ID = inputp('\nYour Blockfrost Mainnet API ID\n(should match the network-specific ID for mainnet - you can override with your testnet ID when testing)\n >Blockfrost Mainnet API ID:', API_ID_INPUT)
    WLENABLEDSTRING = inputp('\nUse a whitelist?\n(if false, any payment received to the watched address will be checked for matching amount params)\n >Enter True or False:', str(WLENABLED_INPUT))
    WLONESTRING = 'False'
    if PROFILE_TYPE == 0:
        if WLENABLEDSTRING == 'True' or WLENABLEDSTRING == 'true':
            WLONESTRING = inputp('\nRemove A Sender Address From Whitelist After 1 Payment is Received?\n >Enter True or False:', str(WHITELIST_ONCE_INPUT))

    # Process these inputs
    if len(CLI_PATH) == 0:
        CLI_PATH = 'cardano-cli'
    NETWORK = 'mainnet'
    API_URI_PRE = 'https://cardano-'
    API_URI_POST = '.blockfrost.io/api/v0/'
    WLENABLED = False
    WHITELIST_ONCE = False
    if WLENABLEDSTRING == 'True' or WLENABLEDSTRING == 'true':
        WLENABLED = True
    if WLONESTRING == 'True' or WLONESTRING == 'true':
        WHITELIST_ONCE = True

    if PROFILE_TYPE == 0:
        WATCH_SKEY_PATH = inputp('\nSigning Key File Path Of Watch Address\n(e.g. /home/user/node/wallets/watch.skey)\n >Watch Address .skey File Path:', WATCH_SKEY_PATH_INPUT)
        WATCH_VKEY_PATH = inputp('\nVerification Key File Path Of Watch Address\n(e.g. /home/user/node/wallet/watch.vkey)\n >Watch Address .vkey File Path:', WATCH_VKEY_PATH_INPUT)
        SMARTCONTRACT_PATH = inputp('\nSmart Contract Plutus File Path\n(path to the ".plutus" file - leave blank if you will be using the built-in simple token swap contract)\n >Smart Contract File Path:', SMARTCONTRACT_PATH_INPUT)
        TOKEN_POLICY_ID = inputp('\nToken Policy ID Of Token To Be Deposited To Smart Contract\n(the long string before the dot)\n >Token Policy ID:', TOKEN_POLICY_ID_INPUT)
        TOKEN_NAME = inputp('\nToken Name Of Token To Be Deposited To Smart Contract\n(comes after the dot after the policy ID)\n >Token Name:', TOKEN_NAME_INPUT)
        print('\n\nNOTE: The following amount responses should all be\n      entered in Lovelace e.g. 1.5 ADA = 1500000\n\n')
        RETURN_ADA = inputp('\nAmount Of Lovelace To Include With Each Swap Transaction\n(cannot be below protocol limit)\n >Included ADA Amount in Lovelace:', RETURN_ADA_INPUT)
        EXPECT_ADA = inputp('\nAmount Of Lovelace To Watch For\n(this is the amount SeaMonk is watching the wallet for)\n >Watch-for Amount in Lovelace:', EXPECT_ADA_INPUT)
        MININPUT = '0'
        if not EXPECT_ADA:
            MININPUT = inputp('\nMinimum Amount of Lovelace To Watch For\n(minimum to watch for when watching for "any" amount)\n >Watch-for Min Amount in Lovelace:', str(MIN_WATCH_INPUT))
            TOKEN_QTY = inputp('\nDynamic Token Quantity (Per-ADA) To Be Sent In Each Swap Transaction\n(how many tokens-per-ADA to send with each successful matched transaction swap, e.g. putting 100 means 100 Tokens per 1 ADA sent by a user)\n >Tokens Per 1 ADA:', TOKEN_QTY_INPUT)
        else:
            TOKEN_QTY = inputp('\nStatic Token Quantity To Be Sent In Each Swap Transaction\n(how many tokens to send with each successful matched transaction swap)\n >Token Amount To Swap Per TX:', TOKEN_QTY_INPUT)
        PRICE = inputp('\nPrice If Any To Be Paid To Watch Address\n(this is not the amount being watched for)\n >Price Amount in Lovelace:', PRICE_INPUT)
        COLLATSTRING = inputp('\nAmount Of Lovelace Collateral To Include\n(required for smartcontract tx, usually 2000000)\n >Collateral Amount in Lovelace:', str(COLLATERAL_INPUT))
        
        print('\n\nAfter this setup and any smart-contract generating, you will need to deposit into the smart contract by running: "python3 seamonk.py --option deposit". The following inputs are related to deposits. For auto-replenishing a smart-contract wherein you are sending a large amount to be processed in smaller batches, the token quantity you enter in the following input, will apply to each deposit replenish attempt.\n\n')
        DEPOSIT_AMNT = inputp('\nQuantity of Tokens You Will Deposit\n(you can enter a batch amount, when it runs low the app will try to replenish with the same batch amount)\n >Quantity of ' + TOKEN_NAME +' Tokens to Deposit:', DEPOSIT_AMNT_INPUT)
        RECURRINGSTRING = inputp('\nIs This A Recurring Amount?\n(type True or False)\n >Recurring Deposit? ', str(RECURRINGSTRING_INPUT))
        SC_ADA_AMNT = inputp('\nAmount Of Lovelace To Be At UTxO On SmartContract\n(cannot be lower than protocol, 2 ADA is recommended for most cases)\n >Amount in Lovelace:', SC_ADA_AMNT_INPUT)
        WT_ADA_AMNT = inputp('\nAmount Of Lovelace To Be At UTxO Of Token Change At Watched Wallet\n(cannot be lower than protocol, 2 ADA is recommended for most cases)\n >Amount in Lovelace:', WT_ADA_AMNT_INPUT)
        AUTO_REFUNDSTRING = inputp('\nAutomatically Refund Payments Too Large?\n(type True or False - this will enable auto-refunds for payments which exceed the tokens ever available for swap by the SmartContract)\n >Refunds Enabled?', str(AUTO_REFUND_INPUT))
        FEE_CHARGEINPUT = inputp('\nFee To Charge For Refunds\n(rather than simply deducting a protocol fee, setting a higher fee discourages abuse and more attentive participation..if left blank default is 500000 lovelace)\n >Fee Charged For Refunds in Lovelace:', str(FEE_CHARGE_INPUT))
        if len(SMARTCONTRACT_PATH) == 0:
            SMARTCONTRACT_PATH = log + UNIQUE_NAME + '.plutus'
        COLLATERAL = int(COLLATSTRING)
        MIN_WATCH = int(MININPUT)
        if not FEE_CHARGEINPUT:
            FEE_CHARGEINPUT = "500000"
        FEE_CHARGE = int(FEE_CHARGEINPUT)
        RECURRING = False
        AUTO_REFUND = False
        if RECURRINGSTRING == 'True' or RECURRINGSTRING == 'true':
            RECURRING = True
        if AUTO_REFUNDSTRING == 'True' or AUTO_REFUNDSTRING == 'true':
            AUTO_REFUND = True
        
        # Save to dictionary
        rawSettings = {'type':PROFILE_TYPE,'log':log,'cache':cache,'txlog':txlog,'network':NETWORK,'cli_path':CLI_PATH,'api_pre':API_URI_PRE,'api_post':API_URI_POST,'api':API_ID,'collateral':COLLATERAL,'wlenabled':WLENABLED,'wlone':WHITELIST_ONCE,'watchskey':WATCH_SKEY_PATH,'watchvkey':WATCH_VKEY_PATH,'scpath':SMARTCONTRACT_PATH,'tokenid':TOKEN_POLICY_ID,'tokenname':TOKEN_NAME,'expectada':EXPECT_ADA,'min_watch':MIN_WATCH,'price':PRICE,'tokenqty':TOKEN_QTY,'returnada':RETURN_ADA,'deposit_amnt':DEPOSIT_AMNT,'recurring':RECURRING,'sc_ada_amnt':SC_ADA_AMNT,'wt_ada_amnt':WT_ADA_AMNT, 'auto_refund':AUTO_REFUND, 'fee_to_charge':FEE_CHARGE}

    if PROFILE_TYPE == 1:
        if reconfig:
            input('\nThis reconfiguration function will OVERWRITE your current json, svg, and html files! Are you sure you want to proceed? (press any key to continue)...')
            print('\nContinuing...\n\n')
        MINT_LAST_TIP = ''
        AUCTIONINPUT = inputp('\nAuction style 0 = Traditional, Highest Cumulative Bid Wins in Timeframe; 1 = Guess the Secret Reserve:', AUCTIONINPUT)
        AUCTION = int(AUCTIONINPUT)
        if AUCTION == 1:
            EXPECT_ADA = input('\nExact Amount Of Lovelace To Watch For\n(this is the amount SeaMonk is watching the wallet for, leave blank if watching for any amount over a certain amount)\n >Exact Watch-for Amount in Lovelace:')
            MININPUT = '0'
            if not EXPECT_ADA:
                MININPUT = input('\nMinimum Amount of Lovelace To Watch For\n(minimum to watch for when watching for "any" amount)\n >Watch-for Min Amount in Lovelace:')
        if AUCTION == 0:
            RESERVE = input('\nSet a Reserve Price? (Yes or No):')
            MININPUT = '0'
            EXPECT_ADA = ''
            if RESERVE == 'yes' or RESERVE == 'Yes':
                MININPUT = input('\nReserve Amount in Lovelace:')
            BLOCKTIMEINPUT = inputp('\nHours Until Auction Close?\n(default is 24 --Enter the hours number in which to end after the first good bid comes in) >Hours Til Close:', BLOCKTIMEINPUT)
            BLOCKTIME = (int(BLOCKTIMEINPUT) * 60) * 60
        MINT_SKEY = inputp('\nEnter the Minting Wallet Signing Key (.skey) File Path:', MINT_SKEY)
        MINT_VKEY = inputp('\nEnter the Minting Wallet Verification Key (.vkey) File Path:', MINT_VKEY)
        #MINT_ADDR = tx.get_address_pubkeyhash(CLI_PATH, MINT_VKEY)
        #input('\nPress any key to verify that the mint address is correct/what you expect given the skey and vkey files: ' + MINT_ADDR)
        MINT_POLICY_SKEY = inputp('\nEnter the Minting Policy Signing Key (.skey) File Path:', MINT_POLICY_SKEY)
        MINT_POLICY_VKEY = inputp('\nEnter the Minting Policy Verification Key (.vkey) File Path:', MINT_POLICY_VKEY)
        POLICY_HASH = tx.get_address_pubkeyhash(CLI_PATH, MINT_POLICY_VKEY)
        input('\nPress any key to verify that the policy hash is correct/what you expect given the skey and vkey files: ' + POLICY_HASH)
        NFT_ADDR = inputp('\nMint NFT at Winner Address? (type True or False)\n(recommend: True - otherwise it will mint at your watch/mint address and must be sent manually after auction end):', NFT_ADDR)
        if NFT_ADDR == 'True' or NFT_ADDR == 'true':
            NFT_ADDR = True
        RETURN_ADA = inputp('\nAmount Of Lovelace To Include With Minted Asset UTxO\n(cannot be below protocol limit)\n >Included ADA Amount in Lovelace:', RETURN_ADA_INPUT)
        
        # feature not yet supported WATCH_ADDR = inputp('\nWatch Address\n(change this ONLY IF watching an alternate address):', MINT_ADDR)
        MINT_NFT_NAME = inputp('\nNFT or Token Name:', MINT_NFT_NAME)
        MINT_NFT_QTY = inputp('\nQuantity (usually 1 for an NFT):', MINT_NFT_QTY)
        ENTER_TARGET = input('\nUse a Set Target Block Height?\n(Yes or No - Yes = Enter a target slot num; No = Enter a count which will be added to the height at time of minting):')
        if ENTER_TARGET == 'Yes' or ENTER_TARGET == 'yes':
            MINT_TARGET_TIP = inputp('\nEnter the block height slot number matching the profile you are wishing to mint into:', MINT_TARGET_TIP)
        else:
            MINT_LAST_TIP = inputp('\nHow Many Slots To Add Until Locked from Minting Height?\n(1 slot ~ 1 second)\nSlots to Add to Block Height at Minting Time:', MINT_LAST_TIP)
        TOKEN_POLICY_ID_INPUT = inputp('\nEnter the Mainnet Policy ID of a Token To Be Used in Fee Refunding and Alt Pay\n(leave empty to not refund fees or offer alt payment):', TOKEN_POLICY_ID_INPUT)
        if len(TOKEN_POLICY_ID_INPUT) > 0:
            TOKEN_NAME_INPUT = inputp('\nMainnet Token Name for Fee Refunding and Alt Pay\n(comes after the dot after the policy ID)\n >Token Name:', TOKEN_NAME_INPUT)
        else:
            TOKEN_POLICY_ID_INPUT = ''
            TOKEN_NAME_INPUT = ''
        COLLATERAL = 1
        MIN_WATCH = int(MININPUT)

        # process inputs and prepare save data
        print('\nAll manually edit fields should be prepared AFTER this function generates your json file')

        # For passing address for visible string:
        SVG_HTML = input('\nEnter path to SVG file for HTML embedding:')
        SVG_IMG = input('\nIF DIFFERENT, enter path to SVG file for Image meta:')
        if not SVG_HTML:
            SVG_HTML = log + MINT_NFT_NAME + '.svg'
            print('\nPlace your SVG file for this NFT at the following location and name accordingly:',SVG_HTML)
            input('\nOnce the SVG image is in place, press any key to continue...')
        if not SVG_IMG:
            SVG_IMG = SVG_HTML
        # Get raw svg data to embed into HTML
        with open(SVG_HTML, 'r') as img:
            img_src = img.read()

        # Setup files
        template_html = MINTSRC + 'template.html'
        html_out = log + MINT_NFT_NAME + '-temp.html'
        template_json = MINTSRC + 'template_svg_html_onchain.json'
        out_json = log + MINT_NFT_NAME + '-temp.json'

        with open(template_html, 'r') as htmlsrc:
            htmlData = htmlsrc.read()
            htmlsrc.close()
        htmlData = htmlData.replace('__00_BGIMG_00__', ' '.join(img_src.split()))
        # Write to new html file in profile folder
        with open(html_out, 'w') as htmlout:
            htmlout.write(htmlData)
            htmlout.close()

        # Base64 HTML and SVG if applicable for image of NFT
        svg_json = json.dumps(tx.encode_to_base64(SVG_IMG, 'svg'))

        # Save all to JSON file
        with open(template_json, 'r') as jsonsrc:
            jsonData = jsonsrc.read()
            jsonsrc.close()
        jsonData = jsonData.replace('000_NAME_000', ' '.join(MINT_NFT_NAME.split()))
        if svg_json:
            jsonData = jsonData.replace('000_SVG_000', ' '.join(svg_json.split()))
        with open(out_json, 'w') as jsonout:
            jsonout.write(jsonData)
            jsonout.close()
        MINT_NFT_JSON = out_json
        print('\nYour NFT JSON file has been generated, before proceeding do any manual edits, leaving 000_POLICY_ID_000 in-tact for the next stages of processing. JSON File Located At: ', out_json)
        
        # Setup list for NFT data, final field is policy hash, blank until loading app and processing policy vkey
        NFT_DATA = [MINT_NFT_NAME, MINT_NFT_QTY, MINT_NFT_JSON, MINT_TARGET_TIP, MINT_LAST_TIP, '']

        # Save to dictionary
        rawSettings = {'type':PROFILE_TYPE,'log':log,'cache':cache,'txlog':txlog,'collateral':COLLATERAL,'network':NETWORK,'cli_path':CLI_PATH,'api_pre':API_URI_PRE,'api_post':API_URI_POST,'api':API_ID,'expectada':EXPECT_ADA,'min_watch':MIN_WATCH,'wlenabled':WLENABLED,'wlone':WHITELIST_ONCE,'nft_addr':NFT_ADDR,'wallet_skey':MINT_SKEY,'wallet_vkey':MINT_VKEY,'policy_skey':MINT_POLICY_SKEY,'policy_vkey':MINT_POLICY_VKEY,'returnada':RETURN_ADA,'nft_data':NFT_DATA,'tokenid':TOKEN_POLICY_ID_INPUT,'tokenname':TOKEN_NAME_INPUT,'nft_minted':NFT_MINTED,'auction':AUCTION,'blocktime':BLOCKTIME,'auctionend':AUCTIONEND}

    # Save/Update whitelist and profile.json files
    settings_file = 'profile.json'
    is_set_file = os.path.isfile(settings_file)
    if not is_set_file:
        open(settings_file, 'x')
    if not append:
        if reconfig:
            reconfig_profile = json.load(open(settings_file, 'r'))
            reconfig_profile[UNIQUE_NAME] = rawSettings
            jsonSettings = json.dumps(reconfig_profile)
        else:
            writeSettings = {UNIQUE_NAME:rawSettings}
            jsonSettings = json.dumps(writeSettings)
    else:
        append_profile = json.load(open(settings_file, 'r'))
        append_profile[UNIQUE_NAME] = rawSettings
        jsonSettings = json.dumps(append_profile)
    with open(settings_file, 'w') as s_file:
        s_file.write(jsonSettings)
        s_file.close()

    # Setup and save whitelist file
    whitelist_file = log + 'whitelist.txt'
    is_wl_file = os.path.isfile(whitelist_file)
    if not is_wl_file:
        try:
            open(whitelist_file, 'x')
            if not WLENABLED:
                with open(whitelist_file, 'w') as wl_header:
                    wl_header.write('none')
                    wl_header.close()
        except OSError:
            pass
    else:
        if not WLENABLED:
            whitelist_bak = log + 'whitelist.bak-' + strftime("%Y-%m-%d_%H-%M-%S", gmtime())
            shutil.copyfile(whitelist_file, whitelist_bak)
            with open(whitelist_file, 'w') as wl_header:
                wl_header.write('none')
                wl_header.close()

    print('\n\n=========================     Profile Saved      =========================\nIf using more than 1 profile, run with this explicit profile with option\n"--profile ' + UNIQUE_NAME + '" e.g. `python3 seamonk.py --profile ' + UNIQUE_NAME + '`.\n\nExiting . . . \n')
    exit(0)

def tx_logger(default_settings, custom_settings):
    """
    TX Logger Loop
    """
    while True:
        logging_result = tx.log_new_txs(default_settings, custom_settings)
        sleep(2)

def tx_processor(DEFAULT_SETTINGS, CUSTOM_SETTINGS):
    # Defaults Settings
    PROFILE_NAME = DEFAULT_SETTINGS[0]
    PROFILE_TYPE = DEFAULT_SETTINGS[1]
    CLI_PATH = DEFAULT_SETTINGS[2]
    NETWORK = DEFAULT_SETTINGS[3]
    MAGIC = DEFAULT_SETTINGS[4]
    PROFILELOG = DEFAULT_SETTINGS[5]
    PROFILECACHE = DEFAULT_SETTINGS[6]
    PROFILETXS = DEFAULT_SETTINGS[7]
    TESTNET = DEFAULT_SETTINGS[8]

    # Dynamic Custom Settings
    API_URI = CUSTOM_SETTINGS[0]
    API_ID = CUSTOM_SETTINGS[1]
    FEE_TOKEN_STRING = CUSTOM_SETTINGS[2]
    PROFILE = CUSTOM_SETTINGS[3]
    MINTSRC = CUSTOM_SETTINGS[4]
    DELAY_TIME = CUSTOM_SETTINGS[5]
    WATCH_ADDR = CUSTOM_SETTINGS[6]
    SMARTCONTRACT_ADDR = CUSTOM_SETTINGS[7]
    MINT_ADDR = CUSTOM_SETTINGS[8]
    WATCH_KEY_HASH = CUSTOM_SETTINGS[9]

    # Shared Settings
    API_URI_PRE = PROFILE['api_pre']
    API_URI_POST = PROFILE['api_post']
    WLENABLED = PROFILE['wlenabled']
    WHITELIST_ONCE = PROFILE['wlone']
    EXPECT_ADA = PROFILE['expectada']
    MIN_WATCH = PROFILE['min_watch']
    RETURN_ADA = PROFILE['returnada']
    TOKEN_POLICY_ID = PROFILE['tokenid']
    TOKEN_NAME = PROFILE['tokenname']
    COLLATERAL = PROFILE['collateral']
    UPDATEMINTSETTINGS = False
    END_AUCTION = False
    AUCTION = ''
    TALLY = 0
    REFUND_PENDING = False
    LOGGER_SETTINGS = [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING]

    # Vars profile 0 - SmartContract Swap
    if PROFILE_TYPE == 0:
        WATCH_SKEY_PATH = PROFILE['watchskey']
        WATCH_VKEY_PATH = PROFILE['watchvkey']
        SMARTCONTRACT_PATH = PROFILE['scpath']
        PRICE = PROFILE['price']
        TOKEN_QTY = PROFILE['tokenqty']
        DEPOSIT_AMNT = PROFILE['deposit_amnt']
        RECURRING = PROFILE['recurring']
        SC_ADA_AMNT = PROFILE['sc_ada_amnt']
        WT_ADA_AMNT = PROFILE['wt_ada_amnt']
        AUTO_REFUND = PROFILE['auto_refund']
        FEE_CHARGE = PROFILE['fee_to_charge']

        # Calculate the "fingerprint" and finalize other variables
        FINGERPRINT = tx.get_token_identifier(TOKEN_POLICY_ID, TOKEN_NAME)
        DATUM_HASH  = tx.get_hash_value(DEFAULT_SETTINGS, '"{}"'.format(FINGERPRINT)).replace('\n', '')
    
    # Vars profile 1 - NFT AutoMinting
    if PROFILE_TYPE == 1:
        NFT_MINTED = PROFILE['nft_minted']
        NFT_ADDR = PROFILE['nft_addr']
        MINT_SKEY = PROFILE['wallet_skey'] # Similar to WATCH_SKEY_PATH
        MINT_VKEY = PROFILE['wallet_vkey']
        MINT_POLICY_SKEY = PROFILE['policy_skey'] # Additional not used by others
        MINT_POLICY_VKEY = PROFILE['policy_vkey']
        NFT_DATA = PROFILE['nft_data']
        AUCTION = PROFILE['auction']
        BLOCKTIME = PROFILE['blocktime']
        AUCTIONEND = PROFILE['auctionend']

    # Instantiate log for profile
    runlog_file = PROFILELOG + 'run.log'
    is_runlog_file = os.path.isfile(runlog_file)
    if not is_runlog_file:
        try:
            open(runlog_file, 'x')
        except OSError:
            pass
    with open(runlog_file, 'a') as runlog:
        time_now = strftime("%Y-%m-%d %H:%M:%S", gmtime())
        runlog.write('\n===============================\n          Begin Process Run at: ' + time_now + '\n===============================\n')
        runlog.close()

    # Begin main payment checking/recording loop here
    while True:
        """
        Main loop: Check for payment, initiate Smart Contract on success
        """
        sleep(2) # Small Delay Improves CPU usage
        result = 'none'
        whitelist_file = PROFILELOG + 'whitelist.txt'
        is_whitelist_file = os.path.isfile(whitelist_file)
        if not is_whitelist_file:
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nMissing expected file: whitelist.txt in your profile folder\n')
                runlog.close()
            print('\nMissing Whitelist (whitelist.txt)! Exiting.\n')
            exit(0)
        whitelist_r = open(whitelist_file, 'r')
        windex = 0
        
        # Foreach line of the whitelist file
        for waddr in whitelist_r:
            # Check if whitelist is empty and end app if it is
            windex += 1
            if not EXPECT_ADA:
                EXPECT_ADA = 0
            RECIPIENT_ADDR = waddr.strip()
            tx.log_new_txs(DEFAULT_SETTINGS, LOGGER_SETTINGS)
            result = tx.check_for_payment(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, EXPECT_ADA, MIN_WATCH, RECIPIENT_ADDR, AUCTION, SMARTCONTRACT_ADDR])
            RESLIST = result.split(',')
            TX_HASH = RESLIST[0].strip()
            RECIPIENT_ADDR = RESLIST[1].strip()
            ADA_RECVD = int(RESLIST[2])
            TK_AMT = int(RESLIST[3])
            TK_NAME = RESLIST[4].strip()
            STAT = int(RESLIST[5])
            TX_TIME = RESLIST[6]
            TALLY = RESLIST[7]

            print('\n Stat:')
            print(STAT)

            # Archive internal TXs and continue
            if STAT == 2:
                continue

            # If a SC Swap
            if PROFILE_TYPE == 0:
                if STAT == 0:
                    # Archive TX and continue for now, may need to refund in future for catching small/under limit tx and auto refunding
                    tx.archive_tx(DEFAULT_SETTINGS, [TX_HASH, ADA_RECVD, TX_TIME])
                    continue
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\n===== Matching TX: '+str(result)+' =====\nRunning whitelist for addr/ada-rec: '+RECIPIENT_ADDR+' | '+str(ADA_RECVD))
                    runlog.close()
                TOKENS_TOSWAP = 0
                if MIN_WATCH > 0:
                    RET_INT = int(RETURN_ADA)
                    ADA_TOSWAP = ADA_RECVD - RET_INT
                    TOKENS_TOSWAP = int((int(TOKEN_QTY) * ADA_TOSWAP) / 1000000)

                # Get SC Token Balance and Compare
                tx.get_utxo(DEFAULT_SETTINGS, SMARTCONTRACT_ADDR, 'utxo_script_check.json')
                if isfile(PROFILECACHE+'utxo_script_check.json') is False:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nERROR: Could not file utxo_script_check.json\n')
                        runlog.close()
                    # Do not archive, continue (keep trying)
                    continue
                _, _, sc_tkns, _, _ = tx.get_txin(DEFAULT_SETTINGS, 'utxo_script_check.json', COLLATERAL, True, DATUM_HASH)
                sc_bal = 0
                for token in sc_tkns:
                    if token != TOKEN_POLICY_ID:
                        continue
                    for t_qty in sc_tkns[token]:
                        sc_bal = int(sc_tkns[token][t_qty])
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nSC Token Balance: '+str(sc_bal))
                    runlog.close()
                if TOKENS_TOSWAP > sc_bal:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nSupply of SC is lower than swap!')
                        runlog.close()
                    if TOKENS_TOSWAP > int(DEPOSIT_AMNT):
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nTokens requested exceeds any future deposit currently set. Refunding user, minus fees')
                            runlog.close()
                        if AUTO_REFUND:
                            REFUND_AMNT = ADA_RECVD - FEE_CHARGE
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nRefunding (tokens exceed): '+str(REFUND_AMNT))
                                runlog.close()
                            filePre = 'refundTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                            tx_refund_a_hash = withdraw(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, RETURN_ADA, PRICE, COLLATERAL, REFUND_AMNT, 0, 0])

                            if tx_refund_a_hash != 'error':
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                    runlog.close()
                            else:
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nTX attempted, error returned by withdraw')
                                    runlog.close()
                                # continue to try again (no archive yet)
                                continue

                            # Record the payment as completed, leave whitelist untouched since not a valid swap tx
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                runlog.close()
                            payments_file = PROFILELOG + 'payments.log'
                            with open(payments_file, 'a') as payments_a:
                                payments_a.write(result + '\n')
                                payments_a.close()

                        # TODO: May need to improve this logic for missed if statement cases
                        continue
                
                    # Refresh Low SC Balance
                    if RECURRING:
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nRecurring deposits enabled, attempting to replenish SC...')
                            runlog.close()
                        CHECK_PRICE = 0
                        if EXPECT_ADA != PRICE:
                            CHECK_PRICE = int(PRICE)
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('Price set as: '+str(CHECK_PRICE))
                                runlog.close()
                        filePre = 'replenishSC_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                        tx_rsc_hash = deposit(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DEPOSIT_AMNT, SC_ADA_AMNT, WT_ADA_AMNT, DATUM_HASH, CHECK_PRICE, COLLATERAL, TOKENS_TOSWAP, RECIPIENT_ADDR, True])
                        if tx_rsc_hash != 'error':
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                runlog.close()
                        else:
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nTX attempted, error returned by withdraw')
                                runlog.close()
                            # continue and try again (do not archive yet)
                            continue

                        # Record the payment as completed and remove from whitelist if set to true
                        payments_file = PROFILELOG + 'payments.log'
                        with open(payments_file, 'a') as payments_a:
                            payments_a.write(result + '\n')
                            payments_a.close()
                    
                        # Remove from whitelist if necessary
                        if WLENABLED and WHITELIST_ONCE:
                            clean_wlws = RECIPIENT_ADDR
                            with open(whitelist_file,'r') as read_file:
                                lines = read_file.readlines()
                            currentLine = 0
                            with open(whitelist_file,'w') as write_file:
                                for line in lines:
                                    if line.strip('\n') != clean_wlws:
                                        write_file.write(line)
                            read_file.close()
                            write_file.close()
                        continue
                    else:
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nNot a recurring-deposit profile (will try to refund): addr:'+RECIPIENT_ADDR+' | tokens:'+str(TOKENS_TOSWAP)+' | ada:'+str(ADA_RECVD))
                            runlog.close()
                        if AUTO_REFUND:
                            REFUND_AMNT = TOKENS_TOSWAP - FEE_CHARGE
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nSending Refund: '+str(REFUND_AMNT))
                                runlog.close()
                            filePre = 'refundTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                            tx_refund_b_hash = withdraw(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, RETURN_ADA, PRICE, COLLATERAL, REFUND_AMNT, 0, 0])

                            if tx_refund_b_hash != 'error':
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                    runlog.close()
                            else:
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nTX attempted, error returned by withdraw')
                                    runlog.close()
                                # continue to try again (no archive yet)
                                continue
                        else:
                            # Archive completed TX
                            tx.archive_tx(DEFAULT_SETTINGS, [TX_HASH, ADA_RECVD, TX_TIME])
                        # Record the payment as completed
                        payments_file = PROFILELOG + 'payments.log'
                        with open(payments_file, 'a') as payments_a:
                            payments_a.write(result + '\n')
                            payments_a.close()
                        continue

                # Run swap or minting on matched tx
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nProcess this TX Swap: '+RECIPIENT_ADDR+' | tokens:'+str(TOKENS_TOSWAP)+' | ada:'+str(ADA_RECVD))
                    runlog.close()
                filePre = 'swapTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                type_title = 'SmartContract Swap'
                tx_final_hash = smartcontractswap(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, RETURN_ADA, PRICE, COLLATERAL, TOKENS_TOSWAP])

            if PROFILE_TYPE == 1:
                if STAT == 0 or NFT_MINTED == True:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\n--- Check For Payments Found Refundable NFT TX ---\n')
                        runlog.close()
                    MAGIC_PRICE = EXPECT_ADA
                    if MAGIC_PRICE == 0:
                        MAGIC_PRICE = MIN_WATCH
                    if NFT_MINTED == True:
                        MAGIC_PRICE = 0
                    REFUND_AMNT = ADA_RECVD
                    if len(TOKEN_POLICY_ID) > 0:
                        # Calculate Fee Refund or Token Included - if any
                        TOKEN_STRING = tx.get_token_string_id(TOKEN_POLICY_ID + '.' + TOKEN_NAME)
                        if TK_AMT >= 20 and TK_NAME == TOKEN_STRING:
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nRecieved Tokens, fee refunding: '+str(TK_AMT))
                                runlog.close()
                            REFUND_AMNT = ADA_RECVD + 200000
                            REFUND_TYPE = 2
                        else:
                            REFUND_AMNT = ADA_RECVD
                            REFUND_TYPE = 1
                        # If auction type is Traditional, refund does not include clues
                        if AUCTION == 0 and REFUND_TYPE == 1:
                            REFUND_TYPE = 3
                        if AUCTION == 0 and REFUND_TYPE == 2:
                            REFUND_TYPE = 4
                    # Process the refund and record payment
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nRefunding Bid: '+str(REFUND_AMNT))
                        runlog.close()
                    filePre = 'refundTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                    tx_refund_c_hash = withdraw(DEFAULT_SETTINGS, [API_URI, API_ID, MINT_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, MINT_SKEY, '', '', TOKEN_POLICY_ID, TOKEN_NAME, '', RECIPIENT_ADDR, RETURN_ADA, '', COLLATERAL, REFUND_AMNT, REFUND_TYPE, MAGIC_PRICE])

                    # Record the payment as completed, leave whitelist untouched since not a valid swap tx
                    if tx_refund_c_hash != 'error':
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nHash found, TX completed. Writing to payments.log...')
                            runlog.close()
                        payments_file = PROFILELOG + 'payments.log'
                        with open(payments_file, 'a') as payments_a:
                            payments_a.write(result + '\n')
                            payments_a.close()
                    else:
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nTX attempted, error returned by withdraw')
                            runlog.close()
                        # Do not archive in this case, just continue and try again
                    continue

                # Check auction time and status

                # If Auction is Traditional
                if AUCTION == 0:
                    # If first good bid, set end slot and update settings
                    if AUCTIONEND == 0:
                        _, AUCTIONEND, _ = tx.get_tip(DEFAULT_SETTINGS, BLOCKTIME)
                        AUCTIONEND = int(AUCTIONEND)
                        # Update settings with new endtime set
                        UPDATEMINTSETTINGS = True
                    else:
                        AUCTION_NOW, _, _ = tx.get_tip(DEFAULT_SETTINGS, 0)
                        auction_diff = int(AUCTIONEND) - int(AUCTION_NOW)
                        if auction_diff <= 0:
                            # Setup finalization log file
                            final_file = PROFILELOG + 'final.log'
                            is_final_log = os.path.isfile(final_file)
                            if not is_final_log:
                                try:
                                    open(final_file, 'x')
                                    with open(final_file, 'a') as final_header:
                                        final_header.write('FromAddr,' + 'Amount,' + 'Action\n')
                                        final_header.close()
                                except OSError:
                                    pass
                            UPDATEMINTSETTINGS = True
                            END_AUCTION = True
                            REFUND_PENDING = True
                            NFT_MINTED = True
                            PROFILE['nft_minted'] = NFT_MINTED
                            
                            # Find Winning Bidder
                            highest_addr, highest_tally = tx.process_tally(DEFAULT_SETTINGS)
                            if highest_tally > TALLY:
                                RECIPIENT_ADDR = highest_addr
                                # Set in data to skip archiving on tx submit
                                TX_HASH, ADA_RECVD, TX_TIME = 'mint', highest_tally, strftime("%Y-%m-%d_%H-%M-%S", gmtime())
                                # TODO: check the order of above line and below
                                # Archive this bid tx now, before finalizing winner
                                tx.archive_tx(DEFAULT_SETTINGS, [TX_HASH, ADA_RECVD, TX_TIME])

                # If Auction is Guess
                if AUCTION == 1:
                    UPDATEMINTSETTINGS = True
                    END_AUCTION = True
                    NFT_MINTED = True
                    PROFILE['nft_minted'] = NFT_MINTED

                if UPDATEMINTSETTINGS:
                    # Open and Update
                    UpdateSetFile = 'profile.json'
                    update_minting = json.load(open(UpdateSetFile, 'r'))
                    LOADED = update_minting[PROFILE_NAME]
                    updateMinting = {'type':LOADED['type'],'log':LOADED['log'],'cache':LOADED['cache'],'txlog':LOADED['txlog'],'collateral':LOADED['collateral'],'network':LOADED['network'],'cli_path':LOADED['cli_path'],'api_pre':LOADED['api_pre'],'api_post':LOADED['api_post'],'api':LOADED['api'],'expectada':LOADED['expectada'],'min_watch':LOADED['min_watch'],'wlenabled':LOADED['wlenabled'],'wlone':LOADED['wlone'],'nft_addr':LOADED['nft_addr'],'wallet_skey':LOADED['wallet_skey'],'wallet_vkey':LOADED['wallet_vkey'],'policy_skey':LOADED['policy_skey'],'policy_vkey':LOADED['policy_vkey'],'returnada':LOADED['returnada'],'nft_data':LOADED['nft_data'],'tokenid':LOADED['tokenid'],'tokenname':LOADED['tokenname'],'nft_minted':NFT_MINTED,'auction':LOADED['auction'],'blocktime':LOADED['blocktime'],'auctionend':AUCTIONEND}

                    # Save/Update whitelist and profile.json files
                    update_minting[PROFILE_NAME] = updateMinting
                    jsonOUTSettings = json.dumps(update_minting)
                    with open(UpdateSetFile, 'w') as update_s:
                        update_s.write(jsonOUTSettings)
                        update_s.close()
                    UPDATEMINTSETTINGS = False
                
                if END_AUCTION:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nFound Good NFT TX! Process this TX Mint')
                        runlog.close()
                    filePre = 'Mint_' + NFT_DATA[1] + '-' + NFT_DATA[0] + '_to' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                    type_title = 'NFT AutoMinting'
                    if NFT_ADDR:
                        MINT_AT = RECIPIENT_ADDR
                    else:
                        MINT_AT = MINT_ADDR
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nSet minted flag to True')
                        runlog.write('\nMinting to address: '+MINT_AT+' | json_file:'+NFT_DATA[2]+' | policy_file:'+NFT_DATA[5] + ' | name:' + NFT_DATA[0] + ' | lock:' + NFT_DATA[3])
                        runlog.close()
                    tx_final_hash = mint(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, RETURN_ADA, MINTSRC, MINT_ADDR, MINT_SKEY, MINT_POLICY_SKEY, MINT_AT, NFT_DATA, False])
                else:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nFound Good Bid TX! Record Bid in Payments and in Pending logs')
                        runlog.close()
                    filePre = 'BidPlaced_' + NFT_DATA[1] + '-' + NFT_DATA[0] + '_to' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                    type_title = 'Bid'
                    tx_final_hash = 'bid'
                    # Archive the bid tx received
                    tx.archive_tx(DEFAULT_SETTINGS, [TX_HASH, ADA_RECVD, TX_TIME])

            # With either type watch for TX and record payment
            if tx_final_hash != 'error' or tx_final_hash == 'bid':
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\n' + type_title + ' TX Hash Found: '+tx_final_hash)
                    runlog.close()

                # Record the payment as completed
                payments_file = PROFILELOG + 'payments.log'
                with open(payments_file, 'a') as payments_a:
                    payments_a.write(result + '\n')
                    payments_a.close()

                if WLENABLED and WHITELIST_ONCE:
                    clean_wlws = RECIPIENT_ADDR
                    with open(whitelist_file,'r') as read_file:
                        lines = read_file.readlines()
                    currentLine = 0
                    with open(whitelist_file,'w') as write_file:
                        for line in lines:
                            if line.strip('\n') != clean_wlws:
                                write_file.write(line)
                    read_file.close()
                    write_file.close()
                # Loop and process all non-winning bid tallys if auction ended
                if END_AUCTION and REFUND_PENDING:
                    with open(final_file, 'r') as final_r:
                        readfi = 0
                        last_tally = 0
                        tally = amount

                        # Iterate over file lines
                        for final_line in final_r:
                            if readfi == 0:
                                readfi += 1
                                continue
                            readfi += 1
                            fl = final_line.split(',')
                            if fl[2] == 'won':
                                continue
                            TX_HASH, ADA_RECVD, TX_TIME = 'none', 0, 0
                            REFUND_ADDR = fl[0]
                            REFUND_AMT = fl[1]
                            MAGIC_PRICE = 0
                            # TODO: Refund_type for these cumulative refunds!
                            tx_end_refund_hash = withdraw(DEFAULT_SETTINGS, [API_URI, API_ID, MINT_ADDR, FEE_TOKEN_STRING, filePre, TX_HASH, ADA_RECVD, TX_TIME, MINT_SKEY, '', '', TOKEN_POLICY_ID, TOKEN_NAME, '', REFUND_ADDR, RETURN_ADA, '', COLLATERAL, REFUND_AMT, REFUND_TYPE, MAGIC_PRICE])

                            # Record the payment as completed, leave whitelist untouched since not a valid swap tx
                            if tx_end_refund_hash != 'error':
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nRefund completed for:' + REFUND_ADDR + ' in amount of ' + REFUND_AMT)
                                    runlog.close()
                            else:
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nRefund TX attempted, error returned by withdraw for address and amount:' + REFUND_ADDR + ' | ' + REFUND_AMT)
                                    runlog.close()
                            continue
            else:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\n' + type_title + ' Failed: '+RECIPIENT_ADDR+' | '+str(ADA_RECVD))
                    runlog.close()
                # Do not archive, keep trying
        whitelist_r.close()

        # Check again and sleep program for NN seconds
        tx.log_new_txs(DEFAULT_SETTINGS, LOGGER_SETTINGS)
        sleep(DELAY_TIME)

if __name__ == "__main__":
    # Set default program mode
    DELAY_TIME = 30
    running = True

    # Get user options
    arguments = argv[1:]
    shortopts= "pot"
    longopts = ["profile=","option=","testnet="]

    # Setting behaviour for options
    PROFILE_PASSED = ''
    OPTION_PASSED = ''
    TESTNET_OVERRIDE = ''
    options, args = getopt.getopt(arguments, shortopts,longopts)
    for opt, val in options: 
        if opt in ("-p", "--profile"):
            PROFILE_PASSED = str(val)
        elif opt in ("-o", "--option"):
            OPTION_PASSED = str(val)
        elif opt in ("-t", "--testnet"):
            TESTNET_OVERRIDE = str(val)

    # Setup Temp Directory (try to)
    scptroot = os.path.realpath(os.path.dirname(__file__))
    APPROOT = os.path.join(scptroot, '')
    SRC = os.path.join(os.path.join(scptroot, 'smartcontract-src'), '')
    MINTSRC = os.path.join(os.path.join(scptroot, 'minting-src'), '')

    logname = 'profiles'
    logpath = os.path.join(scptroot, logname)
    LOGROOT = os.path.join(logpath, '')

    mintlogname = 'minted'
    mintlogpath = os.path.join(scptroot, mintlogname)
    MINTROOT = os.path.join(mintlogpath, '')

    try:
        os.mkdir(mintlogname)
    except OSError:
        pass
    try:
        os.mkdir(logname)
    except OSError:
        pass

    # Pre-Profile Functions (such as manual minting)
    if len(OPTION_PASSED) > 0:
        # TODO: Update with new vars
        if OPTION_PASSED == 'mint':
            TESTNET = False
            MINT_NETWORK = 'mainnet'
            MINT_ADDR = 'none'
            MINT_TARGET_TIP = '0'
            MINT_LAST_TIP = '0'
            print('\n    ==============================================================')
            print('    === Welcome to SeaMonk Native Token Simple Minting (beta)! ===')
            print('    ==============================================================')
            print('\n\n    Mint NFTs or Tokens. To mint multiple NFTs into a single\n    policy ID, mint the first NFT and take note of the Policy\n    Locking Slot Number that outputs at the end, for subsequent\n    mintings, use this same Locking Slot Number and they will be\n    minted under the same Policy ID (as long as that slot number\n    is more than 2 minutes into the future)')
            MINT_CLI = input('\nCardano CLI path (or leave blank if in system path):')
            if len(MINT_CLI) == 0:
                MINT_CLI = 'cardano-cli'
            MINT_NETWORK = input('\nEnter the Network Type (mainnet or testnet):')
            if MINT_NETWORK == 'testnet':
                TESTNET = True
                MINT_MAGIC = input('\nTestnet Magic Number:')
                MINT_NETWORK = MINT_NETWORK + '-magic'
            MINT_SKEY = input('\nEnter the Minting Wallet Signing Key (.skey) File Path:')
            MINT_VKEY = input('\nEnter the Minting Wallet Verification Key (.vkey) File Path:')
            MINT_POLICY_SKEY = input('\nEnter the Minting Policy Signing Key (.skey) File Path:')
            MINT_POLICY_VKEY = input('\nEnter the Minting Policy Verification Key (.vkey) File Path:')
            NFT_ADDR = input('\nNFT or Token Recipient Address\n(or leave blank to mint at the same address as your minting wallet skey):')
            MINT_NFT_NAME = input('\nNFT or Token Name:')

            # Setup profile-specific cache and log folders
            LOG = os.path.join(os.path.join(MINTROOT, MINT_NFT_NAME), '')
            CACHE = os.path.join(os.path.join(LOG, 'cache'), '')
            TXLOG = os.path.join(os.path.join(LOG, 'txs'), '')
            try:
                os.mkdir(LOG)
            except OSError:
                pass
            try:
                os.mkdir(CACHE)
            except OSError:
                pass
            try:
                os.mkdir(TXLOG)
            except OSError:
                pass
            
            # Instantiate log for profile
            runlog_file = LOG + 'run.log'
            is_runlog_file = os.path.isfile(runlog_file)
            if not is_runlog_file:
                try:
                    open(runlog_file, 'x')
                except OSError:
                    pass

            MINT_NFT_QTY = input('\nQuantity (usually 1 for an NFT):')
            PREP_JSON = input('\nPrepare and use the svg-html json template? (yes or no):')
            if PREP_JSON == 'yes' or PREP_JSON == 'Yes':
                print('\nAll manually edit fields should be prepared AFTER this function generates your json file')

                # For passing address for visible string:
                NFT_CUSTOM = input('\nValue for "Minting Master" field (buyers address):')
                SVG_HTML = input('\nEnter path to SVG file for HTML embedding:')
                SVG_IMG = input('\nIF DIFFERENT, enter path to SVG file for Image meta:')
                if not SVG_HTML:
                    SVG_HTML = LOG + MINT_NFT_NAME + '.svg'
                    print('\nPlace your SVG file for this NFT at the following location and name accordingly:',SVG_HTML)
                    input('\nOnce the SVG image is in place, press any key to continue...')
                if not SVG_IMG:
                    SVG_IMG = SVG_HTML
                firstpart = NFT_CUSTOM[0:16]
                lastpart = NFT_CUSTOM[-16:]
                s_addr = firstpart + ' . . . ' + lastpart

                # Get raw svg data to embed into HTML
                with open(SVG_HTML, 'r') as img:
                    img_src = img.read()

                # Setup files
                template_html = MINTSRC + 'template.html'
                html_out = LOG + MINT_NFT_NAME + '.html'
                template_json = MINTSRC + 'template_svg_html_onchain.json'
                out_json = LOG + MINT_NFT_NAME + '-temp.json'

                with open(template_html, 'r') as htmlsrc:
                    htmlData = htmlsrc.read()
                    htmlsrc.close()
                htmlData = htmlData.replace('__00_BGIMG_00__', ' '.join(img_src.split()))
                htmlData = htmlData.replace('__00_ADDRL_00__', ' '.join(NFT_CUSTOM.split()))
                htmlData = htmlData.replace('__00_ADDR_00__', ' '.join(s_addr.split()))
                # Write to new html file in profile folder
                with open(html_out, 'w') as htmlout:
                    htmlout.write(htmlData)
                    htmlout.close()

                # Base64 HTML and SVG if applicable for image of NFT
                html_json = json.dumps(tx.encode_to_base64(html_out, 'html'))
                svg_json = json.dumps(tx.encode_to_base64(SVG_IMG, 'svg'))

                # Save all to JSON file
                with open(template_json, 'r') as jsonsrc:
                    jsonData = jsonsrc.read()
                    jsonsrc.close()
                jsonData = jsonData.replace('000_NAME_000', ' '.join(MINT_NFT_NAME.split()))
                if html_json:
                    jsonData = jsonData.replace('000_FILE_000', ' '.join(html_json.split()))
                if svg_json:
                    jsonData = jsonData.replace('000_SVG_000', ' '.join(svg_json.split()))
                with open(out_json, 'w') as jsonout:
                    jsonout.write(jsonData)
                    jsonout.close()
                MINT_NFT_JSON = out_json
                print('\nYour NFT JSON file has been generated, before proceeding do any manual edits, leaving 000_POLICY_ID_000 in-tact for the next stages of processing. JSON File Located At: ', out_json)

            else:
                MINT_NFT_JSON = input('\nPath to this NFT ready-to-mint JSON file\n(Must have 000_POLICY_ID_000 in the policy section and 000_NAME_000 in the main name section, both inside qoutes):')

                # Update provided json and save to this log location
                out_json = LOG + MINT_NFT_NAME + '-temp.json'
                with open(MINT_NFT_JSON, 'r') as jsonsrc:
                    jsonData = jsonsrc.read()
                    jsonsrc.close()
                jsonData = jsonData.replace('000_NAME_000', ' '.join(MINT_NFT_NAME.split()))
                with open(out_json, 'w') as jsonout:
                    jsonout.write(jsonData)
                    jsonout.close()
                MINT_NFT_JSON = out_json
            
            SAME_POLICY = input('\nIs this NFT or Token part of an already existing policy?\n(Yes or No - if this is the first asset minted to a policy answer No):')
            if SAME_POLICY == 'Yes' or SAME_POLICY == 'yes':
                MINT_TARGET_TIP = input('\nEnter the Policy Locking Slot Number matching the policy this NFT or Token will mint into\n(If you lost it you can find it within the ".script" file for a previous asset minted into that policy):')
            else:
                MINT_LAST_TIP = input('\nHow Many Slots To Add Until Locked?\n(1 slot ~ 1 second)\nSlots to Add to Current Block Height:')
            print('\n...Building TX')

            POLICY_HASH = tx.get_address_pubkeyhash(MINT_CLI, MINT_POLICY_VKEY)
            NFT_DATA = [MINT_NFT_NAME, MINT_NFT_QTY, MINT_NFT_JSON, MINT_TARGET_TIP, MINT_LAST_TIP, POLICY_HASH]
            DEFAULT_SETTINGS = ['manual-mintName', 'notype', MINT_CLI, MINT_NETWORK, MINT_MAGIC, LOG, CACHE, TXLOG, TESTNET]
            MINT_ADDR = tx.get_wallet_addr(DEFAULT_SETTINGS, MINT_VKEY)
            if len(NFT_ADDR) == 0:
                NFT_ADDR = tx.get_wallet_addr(DEFAULT_SETTINGS, MINT_VKEY)
            print('\nMAKE CERTAIN YOU HAVE DONE ANY AND ALL MANUAL CHANGES TO THIS NFT META IN THE JSON FILE BEFORE CONTINUING!')
            input('Press any key when ready, to continue...MUST HAVE OVER 5 ADA AT MINTING ADDR')
            input('Are you ABSOLUTELY CERTAIN your json file is ready? You can copy/paste it into pool.pm/test/metadata to make sure!...if you are sure, press any key')
            minted_hash, policyID, policy_tip = mint(DEFAULT_SETTINGS, ['', '', MINT_ADDR, '', 'mint-' + MINT_NFT_NAME, 'mint', '', '', '5000000', MINTSRC, MINT_ADDR, MINT_SKEY, MINT_POLICY_SKEY, NFT_ADDR, NFT_DATA, True])
            print('\nCompleted - (TX Hash return is ' + minted_hash + ')')
            print('\nIMPORTANT: Take note of the following Policy ID and Policy Locking Slot Number. If you will be minting more NFTs to this same Policy ID, you will need to enter the following Policy Locking Slot Number when minting another NFT into this policy.')
            print('\n    > Asset Name: ', policyID + '.' + MINT_NFT_NAME)
            print('\n    > Minted Qty: ', MINT_NFT_QTY)
            print('\n    > Policy ID: ', policyID)
            print('\n    > Policy Locking Slot Number: ', policy_tip)
            exit(0)

    # Setup Settings Dictionary
    settings_file = 'profile.json'
    is_settings_file = os.path.isfile(settings_file)
    if not is_settings_file:
        setup(LOGROOT)
    
    # Get any set profile name
    PROFILE_NAME = ''
    if len(PROFILE_PASSED) > 0:
        PROFILE_NAME = PROFILE_PASSED

    # Load settings
    load_profile = json.load(open(settings_file, 'r'))
    if len(PROFILE_NAME) == 0:
        PROFILE_NAME = list(load_profile.keys())[0]
    PROFILE = load_profile[PROFILE_NAME]

    # Load default/overridable settings
    CLI_PATH = PROFILE['cli_path']
    TESTNET = False
    NETWORK = PROFILE['network']
    API_ID = PROFILE['api']
    API_NET = 'mainnet'
    TOKEN_POLICY_ID = PROFILE['tokenid']
    TOKEN_NAME = PROFILE['tokenname']
    FEE_TOKEN_STRING = ''

    # Update any overrides
    if len(TESTNET_OVERRIDE) > 0:
        OR = TESTNET_OVERRIDE.split(',')
        print('\ninput:')
        print(TESTNET_OVERRIDE)
        if len(OR[0]) > 0 and len(OR[1]) > 0:
            print('network override values set')
            TESTNET = True
            NETWORK = PROFILE['network'] = 'testnet-magic'
            MAGIC = OR[0]
            API_ID = PROFILE['api'] = OR[1]
            API_NET = 'testnet'
        else:
            print('\nError! Missing magic number or API ID, both are required...exiting...')
            exit(0)
        if len(OR[2]) > 0:
            print('token override value set')
            TOKEN = OR[2].split('.')
            TOKEN_POLICY_ID = PROFILE['tokenid'] = TOKEN[0]
            TOKEN_NAME = PROFILE['tokenname'] = TOKEN[1]
        if len(OR[3]) > 0:
            print('block override value set')
            SLOT_OVERRIDE = OR[3]

    # Load Settings
    API_URI = PROFILE['api_pre'] + API_NET + PROFILE['api_post']
    PROFILELOG = PROFILE['log']
    PROFILECACHE = PROFILE['cache']
    PROFILETXLOG = PROFILE['txlog']
    PROFILE_TYPE = PROFILE['type']
    EXPECT_ADA = PROFILE['expectada']
    COLLATERAL = PROFILE['collateral']
    if len(OPTION_PASSED) > 0:
        if OPTION_PASSED == 'reconfigure':
            setup(LOGROOT, PROFILE_NAME, True)
        elif OPTION_PASSED == 'new_profile':
            setup(LOGROOT, PROFILE_NAME, False, True)
        elif OPTION_PASSED == 'get_transactions':
            running = False
        else:
            print('\nOption not recognized, exiting...')
            exit(0)
    
    # Populate main default settings
    DEFAULT_SETTINGS = [PROFILE_NAME, PROFILE_TYPE, CLI_PATH, NETWORK, MAGIC, PROFILELOG, PROFILECACHE, PROFILETXLOG, TESTNET]

    # If profile type is SC swap
    if PROFILE_TYPE == 0:
        # Vars
        WATCH_SKEY_PATH = PROFILE['watchskey']
        WATCH_VKEY_PATH = PROFILE['watchvkey']
        SMARTCONTRACT_PATH = PROFILE['scpath']
        PRICE = PROFILE['price']
        
        # Check for smartcontract file and prompt to create if not found
        sc_file = SMARTCONTRACT_PATH
        is_sc_file = os.path.isfile(sc_file)
        SC_SETTINGS = [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, '', 'none', '', '', APPROOT, SMARTCONTRACT_PATH, SRC, WATCH_KEY_HASH, PRICE]
        if not is_sc_file:
            create_smartcontract(DEFAULT_SETTINGS, SC_SETTINGS)
        
        # Get dynamic data
        WATCH_ADDR = tx.get_wallet_addr(DEFAULT_SETTINGS, WATCH_VKEY_PATH)
        WATCH_KEY_HASH = tx.get_address_pubkeyhash(CLI_PATH, WATCH_VKEY_PATH)
        SC_ADDR = tx.get_smartcontract_addr(DEFAULT_SETTINGS, SMARTCONTRACT_PATH)
        MINT_ADDR = ''

        # Get custom options relevant to this profile type
        if len(OPTION_PASSED) > 1 and len(API_ID) > 1 and len(WATCH_ADDR) > 1:
            if OPTION_PASSED == 'create_smartcontract':
                create_smartcontract(DEFAULT_SETTINGS, SC_SETTINGS)
            if OPTION_PASSED == 'deposit':
                CHECK_PRICE = 0
                if EXPECT_ADA != PRICE:
                    CHECK_PRICE = int(PRICE)
                    print('\nTo check if price amount in wallet: ' + str(CHECK_PRICE))
                DEPOSIT_SETTINGS = [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING, '', 'none', '', '', WATCH_SKEY_PATH, WATCH_VKEY_PATH, WATCH_KEY_HASH, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, CHECK_PRICE, COLLATERAL]
                start_deposit(DEFAULT_SETTINGS, DEPOSIT_SETTINGS)

    # If profile type is auction/minting
    if PROFILE_TYPE == 1:
        if len(TOKEN_POLICY_ID) > 1:
            FEE_TOKEN_STRING = TOKEN_POLICY_ID + '.' + TOKEN_NAME
        MINT_ADDR = tx.get_wallet_addr(DEFAULT_SETTINGS, PROFILE['wallet_vkey'])
        WATCH_ADDR = MINT_ADDR
        SC_ADDR = MINT_ADDR
        WATCH_KEY_HASH = ''
        PROFILE['nft_data'][5] = tx.get_address_pubkeyhash(CLI_PATH, PROFILE['policy_vkey'])

    # Start get_transactions thread
    if running == False:
        # Instantiate log for profile
        runlog_file = PROFILELOG + 'run.log'
        is_runlog_file = os.path.isfile(runlog_file)
        if not is_runlog_file:
            try:
                open(runlog_file, 'x')
            except OSError:
                pass
        with open(runlog_file, 'a') as runlog:
            time_now = strftime("%Y-%m-%d %H:%M:%S", gmtime())
            runlog.write('\n===============================\n          Begin logging transactions at: ' + time_now + '\n===============================\n')
            runlog.close()
        tx_logger(DEFAULT_SETTINGS, [API_URI, API_ID, WATCH_ADDR, FEE_TOKEN_STRING])

    # Start main thread
    if running == True:
        print('\nProfile in mem:')
        print(PROFILE)
        print('\nOther non PROFILE specific in mem:')
        print([API_URI, API_ID, FEE_TOKEN_STRING, MINTSRC, DELAY_TIME])
        print('\nDefault Settings in mem:')
        print(DEFAULT_SETTINGS)
        #exit(0)
        tx_processor(DEFAULT_SETTINGS, [API_URI, API_ID, FEE_TOKEN_STRING, PROFILE, MINTSRC, DELAY_TIME, WATCH_ADDR, SC_ADDR, MINT_ADDR, WATCH_KEY_HASH])