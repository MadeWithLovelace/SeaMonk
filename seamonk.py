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
#from threading import Thread

def inputp(prompt, text):
    def hook():
        readline.insert_text(text)
        readline.redisplay()
    readline.set_pre_input_hook(hook)
    result = input(prompt)
    readline.set_pre_input_hook()
    return result
    
def deposit(profile_name, log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, deposit_amt, sc_ada_amt, ada_amt, datum_hash, check_price, collateral, filePre, tokens_to_swap = 0, recipient_addr = '', replenish = False):
    # Begin log file and clear cache
    runlog_file = log + 'run.log'
    tx.clean_folder(profile_name)
    tx.proto(profile_name)
    tx.get_utxo(profile_name, watch_addr, 'utxo.json')
    
    # Get wallet utxos
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(profile_name, 'utxo.json', collateral)

    # Check for price amount + other needed amounts in watched wallet
    if check_price > 0:
        price = check_price
        fee_buffer = 1000000
        check_price = int(check_price) + int(sc_ada_amt) + int(ada_amt) + int(collateral) + fee_buffer
        if not replenish:
            print('\nCheck Price now: ', check_price)
        is_price_utxo = tx.get_txin(profile_name, 'utxo.json', collateral, False, '', int(check_price))
        if not is_price_utxo:
            if not replenish:
                print("\nNot enough ADA in your wallet to cover Price and Collateral. Add some funds and try again.\n")
                exit(0)

    if not flag: # TODO: Test with different tokens at bridge wallet
        filePreCollat = 'collatRefill_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
        if not replenish:
            print("No collateral UTxO found! Attempting to create...")
        _, until_tip, block = tx.get_tip(profile_name)
        # Setup UTxOs
        tx_out = tx.process_tokens(profile_name, tokens, watch_addr, ['all'], ada_amt) # Process all tokens and change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Create collateral UTxO
        if not replenish:
            print('\nTX Out Settings for Creating Collateral: ', tx_out)
        tx_data = [
            ''
        ]
        tx.build_tx(profile_name, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        # Sign and submit the transaction
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(profile_name, witnesses, filePreCollat)
        if not replenish:
            print('\nSubmitting and waiting for new UTxO to appear on blockchain...')
        tx_hash_collat = tx.submit_tx(profile_name, filePreCollat)
        if not replenish:
            print('\nTX Hash returned: ' + tx_hash_collat)
    
    # Build, sign, and send transaction
    if flag is True:
        _, until_tip, block = tx.get_tip(profile_name)
        
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
        tx_out = tx.process_tokens(profile_name, tokens, watch_addr, ['all'], ada_amt, [token_policy_id, token_name]) # Account for all except token to swap
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # UTxO to replenish collateral
        if tok_new > 0:
            tx_out += tx.process_tokens(profile_name, tokens, watch_addr, [tok_new], ada_amt) # Account for deposited-token change (if any)
        if tokens_to_swap > 0:
            tx_out += tx.process_tokens(profile_name, tokens, recipient_addr, [tokens_to_swap], ada_amt, [token_policy_id, token_name], False) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(profile_name, tokens, smartcontract_addr, [sc_out], sc_ada_amt, [token_policy_id, token_name], False) # Send just the token for swap
        tx_out += '--tx-out-datum-hash', datum_hash
        tx_data = []
        if replenish:
            if sc_out > tok_bal:
                sc_out = tok_bal
            tx.get_utxo(profile_name, smartcontract_addr, 'utxo_script.json')
            if isfile(cache+'utxo_script.json') is False:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nERROR: Could not file utxo_script.json\n')
                    runlog.close()
                return False
            _, _, sc_tokens, _, data_list = tx.get_txin(profile_name, 'utxo_script.json', collateral, True, datum_hash)

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
            tx_out += tx.process_tokens(profile_name, sc_tokens, watch_addr, sc_out_tk, sc_ada_amt) # UTxO to Get SC Tokens Out
            tx_data = [
                '--tx-out-datum-hash', datum_hash,
                '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
                '--tx-in-redeemer-value', '""',
                '--tx-in-script-file', smartcontract_path
            ]

        tx.build_tx(profile_name, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        # Sign and submit the transaction
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(profile_name, witnesses, filePre)
        tx_hash = tx.submit_tx(profile_name, filePre)
    else:
        if not replenish:
            print('\nCollateral UTxO missing or couldn\'t be created! Exiting...\n')
            exit(0)
        tx_hash = 'error'
    return tx_hash

def withdraw(profile_name, log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, datum_hash, recipient_addr, return_ada, price, collateral, filePre, refund_amnt = 0, refund_type = 0, magic_price = 0):
    # Begin log file
    runlog_file = log + 'run.log'

    # Clear the cache
    tx.clean_folder(profile_name)
    tx.proto(profile_name)
    tx.get_utxo(profile_name, watch_addr, 'utxo.json')

    # Run get_txin
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(profile_name, 'utxo.json', collateral)
    
    # Build, Sign, and Send TX
    if flag is True:
        _, until_tip, block = tx.get_tip(profile_name)
        
        token_amnt = ['all']
        if refund_amnt > 0:
            refund_string = recipient_addr + '+' + str(refund_amnt)
            # Check for refund type: 0 = just a simple refund; 1 = include 40 JUDE & any clue; 2 = include any clue
            ct = 0
            if refund_type == 1:
                # Calculate any clue
                if magic_price == 0:
                    ct = 41
                else:
                    clue_diff = magic_price - refund_amnt
                    if clue_diff <= 20:
                        ct = 130
                    if clue_diff >= 80:
                        ct = 50
                clue_token = str(ct)
                refund_string += '+' + clue_token + ' ' + token_policy_id + '.' + token_name
            if refund_type == 2:
                # Calculate any clue
                if magic_price == 0:
                    ct = 1
                else:
                    clue_diff = magic_price - refund_amnt
                    if clue_diff <= 20:
                        ct = 90
                    if clue_diff >= 80:
                        ct = 10
                clue_token = str(ct)
                refund_string += '+' + clue_token + ' ' + token_policy_id + '.' + token_name
            if ct > 0:
                token_amnt = ['except', ct]
            tx_out_refund = ['--tx-out', refund_string] # UTxO to Refund
        tx_out = tx.process_tokens(profile_name, tokens, watch_addr, token_amnt) # Change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if tx_out_refund:
            tx_out += tx_out_refund # The final refund out if any
        tx_data = []
        if refund_amnt == 0:
            tx.get_utxo(profile_name, smartcontract_addr, 'utxo_script.json')
            if isfile(cache+'utxo_script.json') is False:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nERROR: Could not file utxo_script.json\n')
                    runlog.close()
                return False
            _, _, sc_tokens, _, data_list = tx.get_txin(profile_name, 'utxo_script.json', collateral, True, datum_hash)

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
            tx_out += tx.process_tokens(profile_name, sc_tokens, watch_addr, sc_out, return_ada) # UTxO to Get SC Tokens Out
            tx_data = [
                '--tx-out-datum-hash', datum_hash,
                '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
                '--tx-in-redeemer-value', '""',
                '--tx-in-script-file', smartcontract_path
            ]
        tx.build_tx(profile_name, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(profile_name, witnesses, filePre)
        tx_hash = tx.submit_tx(profile_name, filePre)
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nNo collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.\n')
            runlog.close()
        tx_hash = 'error'
    return tx_hash

def smartcontractswap(profile_name, log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, datum_hash, recipient_addr, token_qty, return_ada, price, collateral, filePre):
    # Begin log file
    runlog_file = log + 'run.log'

    # Clear the cache
    tx.clean_folder(profile_name)
    tx.proto(profile_name)
    tx.get_utxo(profile_name, watch_addr, 'utxo.json')
    
    # Run get_txin
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(profile_name, 'utxo.json', collateral)
    
    # Build, Sign, and Send TX
    if flag is True:
        tx.get_utxo(profile_name, smartcontract_addr, 'utxo_script.json')
        if isfile(cache+'utxo_script.json') is False:
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nERROR: Could not file utxo_script.json\n')
                runlog.close()
            return False
        _, _, sc_tokens, _, data_list = tx.get_txin(profile_name, 'utxo_script.json', collateral, True, datum_hash)
        contract_utxo_in = utxo_in
        for key in data_list:
            # A single UTXO with a single datum can be spent
            if data_list[key] == datum_hash:
                contract_utxo_in += ['--tx-in', key]
                break
        _, until_tip, block = tx.get_tip(profile_name)
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
        tx_out = tx.process_tokens(profile_name, sc_tokens, recipient_addr, [sc_out], return_ada) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(profile_name, tokens, watch_addr) # Change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if price:
            tx_out += ['--tx-out', watch_addr + '+' + str(price)] # UTxO for price if set to process price payment
        if sc_new > 0:
            tx_out += tx.process_tokens(profile_name, sc_tokens, smartcontract_addr, [sc_new]) # UTxO to Send Change to Script - MUST BE LAST UTXO FOR DATUM
        tx_data = [
            '--tx-out-datum-hash', datum_hash,
            '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
            '--tx-in-redeemer-value', '""',
            '--tx-in-script-file', smartcontract_path
        ]
        tx.build_tx(profile_name, watch_addr, until_tip, contract_utxo_in, utxo_col, tx_out, tx_data)
        
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(profile_name, witnesses, filePre)
        tx_hash = tx.submit_tx(profile_name, filePre)
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nNo collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.\n')
            runlog.close()
        tx_hash = 'error'
    return tx_hash

def mint(profile_name, src, log, cache, mint_addr, wallet_skey_path, policy_skey_path, nft_addr, return_ada, nft_data, filePre, manual = False):
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
    tx.clean_folder(profile_name)
    tx.proto(profile_name)
    tx.get_utxo(profile_name, mint_addr, 'utxo.json')

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
        latest_tip, _, _ = tx.get_tip(profile_name, 0, until_tip)
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
        _, until_tip, _ = tx.get_tip(profile_name, nft_add)

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
    nft_id = tx.get_token_id(profile_name, out_script)
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
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(profile_name, 'utxo.json')
    
    # Build Raw Temp
    tx_out_own = tx.process_tokens(profile_name, tokens, mint_addr, ['all'], return_ada, '', True, True, return_ada) # ADA Calc Change
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
    fee = tx.build_raw_tx(profile_name, counts, until_tip, utxo_in, utxo_col, tx_out_temp, tx_data, manual)
    reserve_ada = int(return_ada) + int(fee)
    tx_out_own_new = tx.process_tokens(profile_name, tokens, mint_addr, ['all'], return_ada, '', True, True, reserve_ada) # ADA Calc Change
    tx_out = tx_out_own_new
    tx_out += tx_out_nft

    # Build new tx with fees
    tx.build_raw_tx(profile_name, counts, until_tip, utxo_in, utxo_col, tx_out, tx_data, manual, fee)
    
    # Sign and send
    tx.sign_tx(profile_name, witnesses, filePre)
    tx_hash = tx.submit_tx(profile_name, filePre)
    if manual:
        return tx_hash, nft_id, str(until_tip)
    return tx_hash

def start_deposit(profile_name, api_id, log, cache, watch_addr, watch_skey_path, watch_vkey_path, watch_key_hash, smartcontract_path, token_policy_id, token_name, check_price, collateral):
    # Begin log file
    runlog_file = log + 'run.log'

    smartcontract_addr = tx.get_smartcontract_addr(profile_name, smartcontract_path)

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

    # Calculate the "fingerprint"
    FINGERPRINT = tx.get_token_identifier(token_policy_id, token_name) # Not real fingerprint but works
    DATUM_HASH  = tx.get_hash_value(profile_name, '"{}"'.format(FINGERPRINT)).replace('\n', '')
    #print('Datum Hash: ', DATUM_HASH)
    filePre = 'depositSC_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
    tx_hash = deposit(profile_name, log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, deposit_amt, sc_ada_amt, ada_amt, DATUM_HASH, check_price, collateral, filePre)
    print('\nDeposit is processing . . . ')
    tx.log_new_txs(profile_name, api_id, watch_addr)
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

def create_smartcontract(profile_name, approot, sc_path, src, pubkeyhash, price):
    # Load settings to modify
    settings_file = approot + 'profile.json'
    # Load settings
    load_profile = json.load(open(settings_file, 'r'))
    if len(profile_name) == 0:
        profile_name = list(load_profile.keys())[0]
    PROFILE = load_profile[profile_name]
    LOG = PROFILE['log']
    CACHE = PROFILE['cache']
    TXLOG = PROFILE['txlog']
    NETWORK = PROFILE['network']
    MAGIC = PROFILE['magic']
    CLI_PATH = PROFILE['cli_path']
    API_URI = PROFILE['api_uri']
    API_ID = PROFILE['api']
    WATCH_ADDR = PROFILE['watchaddr']
    COLLATERAL = PROFILE['collateral']
    WLENABLED = PROFILE['wlenabled']
    WHITELIST_ONCE = PROFILE['wlone']
    WATCH_SKEY_PATH = PROFILE['watchskey']
    WATCH_VKEY_PATH = PROFILE['watchvkey']
    WATCH_KEY_HASH = PROFILE['watchkeyhash']
    SMARTCONTRACT_PATH = PROFILE['scpath']
    TOKEN_POLICY_ID = PROFILE['tokenid']
    TOKEN_NAME = PROFILE['tokenname']
    EXPECT_ADA = PROFILE['expectada']
    MIN_WATCH = PROFILE['min_watch']
    PRICE = PROFILE['price']
    TOKEN_QTY = PROFILE['tokenqty']
    RETURN_ADA = PROFILE['returnada']
    DEPOSIT_AMNT = PROFILE['deposit_amnt']
    RECURRING = PROFILE['recurring']
    SC_ADA_AMNT = PROFILE['sc_ada_amnt']
    WT_ADA_AMNT = PROFILE['wt_ada_amnt']
    AUTO_REFUND = PROFILE['auto_refund']
    FEE_CHARGE = PROFILE['fee_to_charge']

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
    SC_ADDR = tx.get_smartcontract_addr(profile_name, sc_path)

    # Save to dictionary
    rawSettings = {'type':PROFILE_TYPE,'log':log,'cache':cache,'txlog':txlog,'network':NETWORK,'magic':MAGIC,'cli_path':CLI_PATH,'api_uri':API_URI,'api':API_ID,'watchaddr':WATCH_ADDR,'collateral':COLLATERAL,'wlenabled':WLENABLED,'wlone':WHITELIST_ONCE,'watchskey':WATCH_SKEY_PATH,'watchvkey':WATCH_VKEY_PATH,'watchkeyhash':WATCH_KEY_HASH,'scpath':SMARTCONTRACT_PATH,'scaddr':SC_ADDR,'tokenid':TOKEN_POLICY_ID,'tokenname':TOKEN_NAME,'expectada':EXPECT_ADA,'min_watch':MIN_WATCH,'price':PRICE,'tokenqty':TOKEN_QTY,'returnada':RETURN_ADA,'deposit_amnt':DEPOSIT_AMNT,'recurring':RECURRING,'sc_ada_amnt':SC_ADA_AMNT,'wt_ada_amnt':WT_ADA_AMNT, 'auto_refund':AUTO_REFUND, 'fee_to_charge':FEE_CHARGE}

    # Save/Update whitelist and profile.json files
    reconfig_profile = json.load(open(settings_file, 'r'))
    reconfig_profile[profile_name] = rawSettings
    jsonSettings = json.dumps(reconfig_profile)
    with open(settings_file, 'w') as s_file:
        s_file.write(jsonSettings)
        s_file.close()

    print('\n================ Finished! ================\n > Your SmartContract Address For Your Records Is: ' + SC_ADDR + '\n\n')
    exit(0)

def setup(logroot, profile_name='', reconfig=False, append=False):
    PROFILE_TYPE = ''
    NETWORK_INPUT = ''
    MAGIC_INPUT = ''
    CLI_PATH_INPUT = ''
    API_ID_INPUT = ''
    WATCH_ADDR_INPUT = ''
    COLLATERAL_INPUT = ''
    WLENABLED_INPUT = ''
    WHITELIST_ONCE_INPUT = ''
    WATCH_SKEY_PATH_INPUT = ''
    WATCH_VKEY_PATH_INPUT = ''
    WATCH_KEY_HASH_INPUT = ''
    SMARTCONTRACT_PATH_INPUT = ''
    SC_ADDR = ''
    TOKEN_POLICY_ID_INPUT = ''
    TOKEN_NAME_INPUT = ''
    EXPECT_ADA_INPUT = ''
    MIN_WATCH_INPUT = ''
    PRICE_INPUT = ''
    TOKEN_QTY_INPUT = ''
    RETURN_ADA_INPUT = ''
    DEPOSIT_AMNT_INPUT = ''
    RECURRINGSTRING_INPUT = ''
    SC_ADA_AMNT_INPUT = ''
    WT_ADA_AMNT_INPUT = ''
    AUTO_REFUND_INPUT = ''
    FEE_CHARGE_INPUT = ''

    # For minting only
    MINT_TARGET_TIP = '0'
    MINT_LAST_TIP = '0'

    if reconfig:
        settings_file = 'profile.json'
        # Load settings
        load_profile = json.load(open(settings_file, 'r'))
        if len(profile_name) == 0:
            profile_name = list(load_profile.keys())[0]
        PROFILE = load_profile[profile_name]
        PROFILE_TYPE = int(PROFILE['type'])
        ### LOG
        ### CACHE
        ### TXLOG
        NETWORK_INPUT = PROFILE['network']
        if NETWORK_INPUT == 'testnet-magic':
            NETWORK_INPUT = 'testnet'
        MAGIC_INPUT = PROFILE['magic']
        CLI_PATH_INPUT = PROFILE['cli_path']
        ### API_URI
        API_ID_INPUT = PROFILE['api']
        WATCH_ADDR_INPUT = PROFILE['watchaddr']
        COLLATERAL_INPUT = PROFILE['collateral']
        WLENABLED_INPUT = PROFILE['wlenabled']
        WHITELIST_ONCE_INPUT = PROFILE['wlone']
        WATCH_SKEY_PATH_INPUT = PROFILE['watchskey']
        WATCH_VKEY_PATH_INPUT = PROFILE['watchvkey']
        WATCH_KEY_HASH_INPUT = PROFILE['watchkeyhash']
        SMARTCONTRACT_PATH_INPUT = PROFILE['scpath']
        SC_ADDR = PROFILE['scaddr']
        TOKEN_POLICY_ID_INPUT = PROFILE['tokenid']
        TOKEN_NAME_INPUT = PROFILE['tokenname']
        EXPECT_ADA_INPUT = PROFILE['expectada']
        MIN_WATCH_INPUT = PROFILE['min_watch']
        PRICE_INPUT = PROFILE['price']
        TOKEN_QTY_INPUT = PROFILE['tokenqty']
        RETURN_ADA_INPUT = PROFILE['returnada']
        DEPOSIT_AMNT_INPUT = PROFILE['deposit_amnt']
        RECURRINGSTRING_INPUT = PROFILE['recurring']
        SC_ADA_AMNT_INPUT = PROFILE['sc_ada_amnt']
        WT_ADA_AMNT_INPUT = PROFILE['wt_ada_amnt']
        AUTO_REFUND_INPUT = PROFILE['auto_refund']
        FEE_CHARGE_INPUT = PROFILE['fee_to_charge']
        
        UNIQUE_NAME = profile_name
        print('\n!!! WARNING !!!\nSettings for profile "' + profile_name + '" are about to be overwritten!\n\nExit now if you do not want to do that.\n\n')
    
    print('\n========================= Setting Up New Profile =========================\n')
    if not reconfig:
        print('\n    Choose profile type by entering the cooresponding number:')
        print('      0 = SmartContract Swap')
        print('      1 = Auto-Minting Swap')
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
    print('need be added and the entire wallet will be whitelisted.\n')

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

    NETWORKINPUT = inputp('\nNetwork Type (enter either mainnet or testnet)\n >Network Type:', NETWORK_INPUT)
    if NETWORKINPUT == 'testnet':
        MAGICINPUT = inputp(' >Testnet Magic:', MAGIC_INPUT)
    CLI_PATH = inputp('\nExplicit Path To "cardano-cli"\n(leave empty if cardano-cli is in your system path and\nit is the version you want to use with this profile)\n >Cardano-CLI Path:', CLI_PATH_INPUT)
    API_ID = inputp('\nYour Blockfrost API ID\n(should match the network-specific ID i.e. mainnet vs testnet)\n >Blockfrost API ID:', API_ID_INPUT)
    WLENABLEDSTRING = inputp('\nUse a whitelist?\n(if false, any payment received to the watched address will be checked for matching amount params)\n >Enter True or False:', str(WLENABLED_INPUT))
    WLONESTRING = 'False'
    if WLENABLEDSTRING == 'True' or WLENABLEDSTRING == 'true':
        WLONESTRING = inputp('\nRemove A Sender Address From Whitelist After 1 Payment is Received?\n >Enter True or False:', str(WHITELIST_ONCE_INPUT))

    # Process these inputs
    if len(CLI_PATH) == 0:
        CLI_PATH = 'cardano-cli'
    NETWORK = 'mainnet'
    MAGIC = ''
    if NETWORKINPUT == 'testnet':
        NETWORK = 'testnet-magic'
        MAGIC = MAGICINPUT
    API_URI = 'https://cardano-' + NETWORKINPUT + '.blockfrost.io/api/v0/'
    WLENABLED = False
    WHITELIST_ONCE = False
    if WLENABLEDSTRING == 'True' or WLENABLEDSTRING == 'true':
        WLENABLED = True
    if WLONESTRING == 'True' or WLONESTRING == 'true':
        WHITELIST_ONCE = True

    if PROFILE_TYPE == 0:
        WATCH_ADDR = inputp('\nWallet Address To Watch For Transactions/Payments\n(this is the address you provide to users or customers)\n >Watch Address:', WATCH_ADDR_INPUT)
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
        WATCH_KEY_HASH = tx.get_address_pubkeyhash(CLI_PATH, WATCH_VKEY_PATH)
        if len(SMARTCONTRACT_PATH) == 0:
            SMARTCONTRACT_PATH = log + UNIQUE_NAME + '.plutus'
        else:
            SC_ADDR = tx.get_smartcontract_addr(profile_name, SMARTCONTRACT_PATH)
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
        rawSettings = {'type':PROFILE_TYPE,'log':log,'cache':cache,'txlog':txlog,'network':NETWORK,'magic':MAGIC,'cli_path':CLI_PATH,'api_uri':API_URI,'api':API_ID,'watchaddr':WATCH_ADDR,'collateral':COLLATERAL,'wlenabled':WLENABLED,'wlone':WHITELIST_ONCE,'watchskey':WATCH_SKEY_PATH,'watchvkey':WATCH_VKEY_PATH,'watchkeyhash':WATCH_KEY_HASH,'scpath':SMARTCONTRACT_PATH,'scaddr':SC_ADDR,'tokenid':TOKEN_POLICY_ID,'tokenname':TOKEN_NAME,'expectada':EXPECT_ADA,'min_watch':MIN_WATCH,'price':PRICE,'tokenqty':TOKEN_QTY,'returnada':RETURN_ADA,'deposit_amnt':DEPOSIT_AMNT,'recurring':RECURRING,'sc_ada_amnt':SC_ADA_AMNT,'wt_ada_amnt':WT_ADA_AMNT, 'auto_refund':AUTO_REFUND, 'fee_to_charge':FEE_CHARGE}

    if PROFILE_TYPE == 1:
        NFT_ADDR = ''
        MINT_LAST_TIP = '0'
        MINT_SKEY = input('\nEnter the Minting Wallet Signing Key (.skey) File Path:')
        MINT_VKEY = input('\nEnter the Minting Wallet Verification Key (.vkey) File Path:')
        PROFTEMP = [CLI_PATH, NETWORK, MAGIC, '', '', '']
        MINT_ADDR = tx.get_wallet_addr(PROFTEMP, MINT_VKEY)
        WATCH_ADDR = MINT_ADDR
        MINT_POLICY_SKEY = input('\nEnter the Minting Policy Signing Key (.skey) File Path:')
        MINT_POLICY_VKEY = input('\nEnter the Minting Policy Verification Key (.vkey) File Path:')
        NFT_ADDR = input('\nNFT or Token Recipient Address\n(or leave blank to mint at swappers address):')
        RETURN_ADA = input('\nAmount Of Lovelace To Include With Minted Asset UTxO\n(cannot be below protocol limit)\n >Included ADA Amount in Lovelace:')
        EXPECT_ADA = input('\nExact Amount Of Lovelace To Watch For\n(this is the amount SeaMonk is watching the wallet for, leave blank if watching for any amount over a certain amount)\n >Exact Watch-for Amount in Lovelace:')
        MININPUT = '0'
        if not EXPECT_ADA:
            MININPUT = input('\nMinimum Amount of Lovelace To Watch For\n(minimum to watch for when watching for "any" amount)\n >Watch-for Min Amount in Lovelace:')
        # feature not yet supported WATCH_ADDR = inputp('\nWatch Address\n(change this ONLY IF watching an alternate address):', MINT_ADDR)
        MINT_NFT_NAME = input('\nNFT or Token Name:')
        MINT_NFT_QTY = input('\nQuantity (usually 1 for an NFT):')
        ENTER_TARGET = input('\nUse a Set Target Block Height?\n(Yes or No - Yes = Enter a target slot num; No = Enter a count which will be added to the height at time of minting):')
        if ENTER_TARGET == 'Yes' or ENTER_TARGET == 'yes':
            SAME_POLICY = input('\nDo you already have a target block height? (Yes or No - Yes if you are trying to mint into the same Policy as a previous mint):')
            if SAME_POLICY == 'Yes' or SAME_POLICY == 'yes':
                MINT_TARGET_TIP = input('\nEnter the block height slot number matching the profile you are wishing to mint into:')
            else:
                CURRENT_TIP, _, _ = tx.get_tip(PROFTEMP, 0)
                print('\nAdd slots (about 1 per second) to the current block height, to target a locking timeframe. Current block height:',CURRENT_TIP)
                SLOTS_TO_ADD = input('\nEnter the Slots to Add to ' + str(CURRENT_TIP) + ':')
                MINT_TARGET_TIP = int(CURRENT_TIP) + int(SLOTS_TO_ADD)
                MINT_TARGET_TIP = str(MINT_TARGET_TIP)
                print('\nYour target locking height for this policy id, will be:',MINT_TARGET_TIP)
        else:
            MINT_LAST_TIP = input('\nHow Many Slots To Add Until Locked from Minting Height?\n(1 slot ~ 1 second)\nSlots to Add to Block Height at Minting Time:')
        TOKEN_POLICY_ID = input('\nEnter the Policy ID a Token Used in Fee Refunding and Alt Pay\n(leave empty to not refund fees or offer alt payment):')
        if len(TOKEN_POLICY_ID) > 0:
            TOKEN_NAME = input('\nToken Name for Fee Refunding and Alt Pay\n(comes after the dot after the policy ID)\n >Token Name:')
        else:
            TOKEN_POLICY_ID = ''
            TOKEN_NAME = ''
        COLLATERAL = 2000000
        MIN_WATCH = int(MININPUT)

        # process inputs and prepare save data
        print('\nAll manually edit fields should be prepared AFTER this function generates your json file')

        # For passing address for visible string:
        SVG_HTML = input('\nEnter path to SVG file for HTML embedding:')
        SVG_IMG = input('\nIF DIFFERENT, enter path to SVG file for Image meta:')
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
        input('\nPress any key to continue and save these settings!')
        
        POLICY_HASH = tx.get_address_pubkeyhash(CLI_PATH, MINT_POLICY_VKEY)
        NFT_DATA = [MINT_NFT_NAME, MINT_NFT_QTY, MINT_NFT_JSON, MINT_TARGET_TIP, MINT_LAST_TIP, POLICY_HASH]

        # Save to dictionary
        rawSettings = {'type':PROFILE_TYPE,'log':log,'cache':cache,'txlog':txlog,'collateral':COLLATERAL,'network':NETWORK,'magic':MAGIC,'cli_path':CLI_PATH,'api_uri':API_URI,'api':API_ID,'watchaddr':WATCH_ADDR,'scaddr':MINT_ADDR,'expectada':EXPECT_ADA,'min_watch':MIN_WATCH,'wlenabled':WLENABLED,'wlone':WHITELIST_ONCE,'mint_addr':MINT_ADDR,'nft_addr':NFT_ADDR,'wallet_skey':MINT_SKEY,'policy_skey':MINT_POLICY_SKEY,'returnada':RETURN_ADA,'nft_data':NFT_DATA,'tokenid':TOKEN_POLICY_ID,'tokenname':TOKEN_NAME}

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

def tx_logger(profile_name, api_id, watch_addr):
    while True:
        # Begin checking for txs
        logging_result = tx.log_new_txs(profile_name, api_id, watch_addr)
        sleep(2)

def tx_processor(MINTSRC, PROFILE_NAME, PROFILE):
    # Vars shared
    PROFILE_TYPE = PROFILE['type']
    API_ID = PROFILE['api']
    WATCH_ADDR = PROFILE['watchaddr']
    WLENABLED = PROFILE['wlenabled']
    WHITELIST_ONCE = PROFILE['wlone']
    EXPECT_ADA = PROFILE['expectada']
    MIN_WATCH = PROFILE['min_watch']
    RETURN_ADA = PROFILE['returnada']
    TOKEN_POLICY_ID = PROFILE['tokenid']
    TOKEN_NAME = PROFILE['tokenname']
    COLLATERAL = PROFILE['collateral']

    # Vars profile 0 - SmartContract Swap
    if PROFILE_TYPE == 0:
        WATCH_SKEY_PATH = PROFILE['watchskey']
        WATCH_VKEY_PATH = PROFILE['watchvkey']
        WATCH_KEY_HASH = PROFILE['watchkeyhash']
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
        DATUM_HASH  = tx.get_hash_value(PROFILE_NAME, '"{}"'.format(FINGERPRINT)).replace('\n', '')
        SMARTCONTRACT_ADDR = tx.get_smartcontract_addr(PROFILE_NAME, SMARTCONTRACT_PATH)
    
    # Vars profile 1 - NFT AutoMinting
    if PROFILE_TYPE == 1:
        NFT_MINTED = False
        MINT_ADDR = PROFILE['mint_addr']
        NFT_ADDR = PROFILE['nft_addr']
        MINT_SKEY = PROFILE['wallet_skey'] # Similar to WATCH_SKEY_PATH
        MINT_POLICY_SKEY = PROFILE['policy_skey'] # Additional not used by others
        NFT_DATA = PROFILE['nft_data']

    # Instantiate log and cache folders for profile
    PROFILELOG = PROFILE['log']
    PROFILECACHE = PROFILE['cache']
    PROFILETXS = PROFILE['txlog']

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
        sleep(5) # Small Delay Improves CPU usage
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
            tx.log_new_txs(PROFILE_NAME, API_ID, WATCH_ADDR)
            sleep(5)
            result = tx.check_for_payment(PROFILE_NAME, API_ID, WATCH_ADDR, EXPECT_ADA, MIN_WATCH, RECIPIENT_ADDR)
            RESLIST = result.split(',')
            TX_HASH = RESLIST[0].strip()
            RECIPIENT_ADDR = RESLIST[1].strip()
            ADA_RECVD = int(RESLIST[2])
            TK_AMT = int(RESLIST[3])
            TK_NAME = RESLIST[4].strip()
            STAT = int(RESLIST[5])

            # If a SC Swap
            if PROFILE_TYPE == 0:
                if STAT == 0:
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
                tx.get_utxo(PROFILE_NAME, SMARTCONTRACT_ADDR, 'utxo_script_check.json')
                if isfile(PROFILECACHE+'utxo_script_check.json') is False:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nERROR: Could not file utxo_script_check.json\n')
                        runlog.close()
                _, _, sc_tkns, _, _ = tx.get_txin(PROFILE_NAME, 'utxo_script_check.json', COLLATERAL, True, DATUM_HASH)
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
                            tx_refund_a_hash = withdraw(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, RETURN_ADA, PRICE, COLLATERAL, filePre, REFUND_AMNT)

                            if tx_refund_a_hash != 'error':
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                    runlog.close()
                            else:
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nTX attempted, error returned by withdraw')
                                    runlog.close()
                                continue

                            # Record the payment as completed, leave whitelist untouched since not a valid swap tx
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                runlog.close()
                            payments_file = PROFILELOG + 'payments.log'
                            with open(payments_file, 'a') as payments_a:
                                payments_a.write(result + '\n')
                                payments_a.close()
                        sleep(5)
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
                        tx_rsc_hash = deposit(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DEPOSIT_AMNT, SC_ADA_AMNT, WT_ADA_AMNT, DATUM_HASH, CHECK_PRICE, COLLATERAL, filePre, TOKENS_TOSWAP, RECIPIENT_ADDR, True)

                        if tx_rsc_hash != 'error':
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                runlog.close()
                        else:
                            with open(runlog_file, 'a') as runlog:
                                runlog.write('\nTX attempted, error returned by withdraw')
                                runlog.close()
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
                        sleep(5)
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
                            tx_refund_b_hash = withdraw(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, RETURN_ADA, PRICE, COLLATERAL, filePre, REFUND_AMNT)

                            if tx_refund_b_hash != 'error':
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nRefund hash found, TX completed. Writing to payments.log.')
                                    runlog.close()
                            else:
                                with open(runlog_file, 'a') as runlog:
                                    runlog.write('\nTX attempted, error returned by withdraw')
                                    runlog.close()
                                continue
                        
                        # Record the payment as completed
                        payments_file = PROFILELOG + 'payments.log'
                        with open(payments_file, 'a') as payments_a:
                            payments_a.write(result + '\n')
                            payments_a.close()
                        sleep(5)
                        continue

                # Run swap or minting on matched tx
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nProcess this TX Swap: '+RECIPIENT_ADDR+' | tokens:'+str(TOKENS_TOSWAP)+' | ada:'+str(ADA_RECVD))
                    runlog.close()
                filePre = 'swapTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                type_title = 'SmartContract Swap'
                tx_final_hash = smartcontractswap(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, str(TOKENS_TOSWAP), RETURN_ADA, PRICE, COLLATERAL, filePre)

            if PROFILE_TYPE == 1:
                if STAT == 0 or NFT_MINTED == True:
                    if RECIPIENT_ADDR == MINT_ADDR or RECIPIENT_ADDR == WATCH_ADDR:
                        continue
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
                    # Process the refund and record payment
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nRefunding Bid: '+str(REFUND_AMNT))
                        runlog.close()
                    filePre = 'refundTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                    tx_refund_c_hash = withdraw(PROFILE_NAME, PROFILELOG, PROFILECACHE, MINT_ADDR, MINT_SKEY, '', '', TOKEN_POLICY_ID, TOKEN_NAME, '', RECIPIENT_ADDR, RETURN_ADA, '', COLLATERAL, filePre, REFUND_AMNT, REFUND_TYPE, MAGIC_PRICE)

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
                    continue

                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nFound Good NFT TX! Process this TX Mint')
                    runlog.close()
                filePre = 'Mint_' + NFT_DATA[1] + '-' + NFT_DATA[0] + '_to' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                type_title = 'NFT AutoMinting'
                if NFT_ADDR != MINT_ADDR and NFT_ADDR != WATCH_ADDR and len(NFT_ADDR) == 0:
                    NFT_ADDR = RECIPIENT_ADDR
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nMinting to address: '+NFT_ADDR+' | json_file:'+NFT_DATA[2]+' | policy_file:'+NFT_DATA[5] + ' | name:' + NFT_DATA[0] + ' | lock:' + NFT_DATA[3])
                    runlog.close()
                tx_final_hash = mint(PROFILE_NAME, MINTSRC, PROFILELOG, PROFILECACHE, MINT_ADDR, MINT_SKEY, MINT_POLICY_SKEY, NFT_ADDR, RETURN_ADA, NFT_DATA, filePre)

            # With either type watch for TX and record payment
            if tx_final_hash != 'error':
                if PROFILE_TYPE == 1:
                    NFT_MINTED = True
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nSet minted flag to True')
                        runlog.close()
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
                sleep(5)
            else:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\n' + type_title + ' Failed: '+RECIPIENT_ADDR+' | '+str(ADA_RECVD))
                    runlog.close()
        whitelist_r.close()

        # Check again and sleep program for NN seconds
        tx.log_new_txs(PROFILE_NAME, API_ID, WATCH_ADDR)
        sleep(60)

if __name__ == "__main__":
    # Set default program mode
    running = True

    # Get user options
    arguments = argv[1:]
    shortopts= "svo"
    longopts = ["profile=","option="]

    # Setting behaviour for options
    PROFILE_PASSED = ''
    OPTION_PASSED = ''
    options, args = getopt.getopt(arguments, shortopts,longopts)
    for opt, val in options: 
        if opt in ("-p", "--profile"):
            PROFILE_PASSED = str(val)
        elif opt in ("-o", "--option"):
            OPTION_PASSED = str(val)

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
    API_ID = PROFILE['api']
    WATCH_ADDR = PROFILE['watchaddr']
    PROFILELOG = PROFILE['log']
    PROFILECACHE = PROFILE['cache']
    PROFILE_TYPE = PROFILE['type']
    TOKEN_POLICY_ID = PROFILE['tokenid']
    EXPECT_ADA = PROFILE['expectada']
    COLLATERAL = PROFILE['collateral']

    # Pre-Profile Functions (such as manual minting)
    if len(OPTION_PASSED) > 0:
        if OPTION_PASSED == 'reconfigure':
            setup(LOGROOT, PROFILE_NAME, True)

        if OPTION_PASSED == 'new_profile':
            setup(LOGROOT, PROFILE_NAME, False, True)

        if OPTION_PASSED == 'get_transactions':
            running = False

        if OPTION_PASSED == 'mint':
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
                #input('\nPress any key to continue')

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
            PROFILE = [MINT_CLI, MINT_NETWORK, MINT_MAGIC, LOG, TXLOG, CACHE]
            MINT_ADDR = tx.get_wallet_addr(PROFILE, MINT_VKEY)
            if len(NFT_ADDR) == 0:
                NFT_ADDR = tx.get_wallet_addr(PROFILE, MINT_VKEY)
            minted_hash, policyID, policy_tip = mint(PROFILE, MINTSRC, LOG, CACHE, MINT_ADDR, MINT_SKEY, MINT_POLICY_SKEY, NFT_ADDR, '2000000', NFT_DATA, 'mint-' + MINT_NFT_NAME, True)
            print('\nCompleted - (TX Hash return is ' + minted_hash + ')')
            print('\nIMPORTANT: Take note of the following Policy ID and Policy Locking Slot Number. If you will be minting more NFTs to this same Policy ID, you will need to enter the following Policy Locking Slot Number when minting another NFT into this policy.')
            print('\n    > Asset Name: ', policyID + '.' + MINT_NFT_NAME)
            print('\n    > Minted Qty: ', MINT_NFT_QTY)
            print('\n    > Policy ID: ', policyID)
            print('\n    > Policy Locking Slot Number: ', policy_tip)
            exit(0)

    if PROFILE_TYPE == 0:
        # Vars
        WATCH_SKEY_PATH = PROFILE['watchskey']
        WATCH_VKEY_PATH = PROFILE['watchvkey']
        WATCH_KEY_HASH = PROFILE['watchkeyhash']
        SMARTCONTRACT_PATH = PROFILE['scpath']
        TOKEN_NAME = PROFILE['tokenname']
        PRICE = PROFILE['price']
        
        # Check for smartcontract file and prompt to create if not found
        sc_file = SMARTCONTRACT_PATH
        is_sc_file = os.path.isfile(sc_file)
        if not is_sc_file:
            create_smartcontract(PROFILE_NAME, APPROOT, SMARTCONTRACT_PATH, SRC, WATCH_KEY_HASH, PRICE)

        if len(OPTION_PASSED) > 1 and len(API_ID) > 1 and len(WATCH_ADDR) > 1:
            if OPTION_PASSED == 'create_smartcontract':
                create_smartcontract(PROFILE_NAME, APPROOT, SMARTCONTRACT_PATH, SRC, WATCH_KEY_HASH, PRICE)

            if OPTION_PASSED == 'deposit':
                CHECK_PRICE = 0
                if EXPECT_ADA != PRICE:
                    CHECK_PRICE = int(PRICE)
                    print('\nTo check if price amount in wallet: ' + str(CHECK_PRICE))
                start_deposit(PROFILE_NAME, API_ID, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, WATCH_VKEY_PATH, WATCH_KEY_HASH, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, CHECK_PRICE, COLLATERAL)
        
            if OPTION_PASSED == 'replenish':
                # May be unneeded
                print('\nOption not yet enabled')
                exit(0)
    
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
        #Thread(target=lambda: tx_logger(PROFILE_NAME, API_ID, WATCH_ADDR)).start()
        tx_logger(PROFILE_NAME, API_ID, WATCH_ADDR)

    # Start main thread
    if running == True:
        tx_processor(MINTSRC, PROFILE_NAME, PROFILE)