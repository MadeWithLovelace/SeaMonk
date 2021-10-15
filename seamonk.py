import os
import subprocess
import time
import datetime
import json
import cardanotx as tx
from sys import exit, argv
from os.path import isdir, isfile

def deposit(log, cache, watch_addr, watch_skey_path, smartcontract_addr, token_policy_id, token_name, deposit_amt, sc_ada_amt, ada_amt, datum_hash, collateral):
    # Begin log file
    runlog_file = log + 'run.log'
    
    # Clear the cache
    tx.clean_folder(cache)
    tx.proto(cache)
    tx.get_utxo(watch_addr, cache, 'utxo.json')
    
    # Get wallet utxos
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(log, cache, 'utxo.json', collateral)
    
    # Build, sign, and send transaction
    if flag is True:
        _, until_tip, block = tx.get_tip(cache)
        
        # Calculate token quantity and any change
        tok_bal = 0
        sc_out = int(deposit_amt)
        tok_new = 0
        for token in tokens:
            if token == 'lovelace':
                continue
            for t_qty in tokens[token]:
                tok_bal = tokens[token][t_qty]
                tok_new = tok_bal - sc_out

        # Setup UTxOs
        tx_out = tx.process_tokens(cache, tokens, watch_addr, 'all', ada_amt, [token_policy_id, token_name]) # Account for all except token to swap
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # UTxO to replenish collateral
        if tok_new > 0:
            tx_out += tx.process_tokens(cache, tokens, watch_addr, tok_new, ada_amt) # Account for deposited-token change (if any)
        tx_out += tx.process_tokens(cache, tokens, smartcontract_addr, sc_out, sc_ada_amt, [token_policy_id, token_name], False) # Send just the token for swap
        print('\nTX Out Settings: ', tx_out)
        tx_data = [
            '--tx-out-datum-hash', datum_hash # This has to be the hash of the fingerprint of the token
        ]
        print('\nDatum: ', tx_data)
        tx.build_tx(log, cache, watch_addr, until_tip, utxo_in, utxo_col, tx_out, tx_data)
        
        # Sign and submit the transaction
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(log, cache, witnesses)
        tx.submit_tx(log, cache)
        exit(0)
    else:
        print("No collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.")
        exit(0)

def smartcontractswap(log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, datum_hash, recipient_addr, token_qty, return_ada, price,  collateral):
    # Begin log file
    runlog_file = log + 'run.log'

    # Clear the cache
    tx.clean_folder(cache)
    tx.proto(cache)
    tx.get_utxo(watch_addr, cache, 'utxo.json')
    
    # Run get_txin
    utxo_in, utxo_col, tokens, flag, _ = tx.get_txin(log, cache, 'utxo.json', collateral)
    
    # Build, Sign, and Send TX
    if flag is True:
        tx.get_utxo(smartcontract_addr, cache, 'utxo_script.json')
        if isfile(cache+'utxo_script.json') is False:
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nERROR: Could not file utxo_script.json\n')
                runlog.close()
            exit(0)
        _, _, sc_tokens, _, data_list = tx.get_txin(log, cache, 'utxo_script.json', collateral, True, datum_hash)
        contract_utxo_in = utxo_in
        for key in data_list:
            # A single UTXO with a single datum can be spent
            if data_list[key] == datum_hash:
                contract_utxo_in += ['--tx-in', key]
                break
        _, until_tip, block = tx.get_tip(cache)
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
        tx_out = tx.process_tokens(cache, sc_tokens, recipient_addr, sc_out, return_ada) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(cache, tokens, watch_addr) # Change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if price:
            tx_out += ['--tx-out', watch_addr + '+' + str(price)] # UTxO for price if set to process price payment
        if sc_new > 0:
            tx_out += tx.process_tokens(cache, sc_tokens, smartcontract_addr, sc_new) # UTxO to Send Change to Script - MUST BE LAST UTXO FOR DATUM
        tx_data = [
            '--tx-out-datum-hash', datum_hash,
            '--tx-in-datum-value', '"{}"'.format(tx.get_token_identifier(token_policy_id, token_name)),
            '--tx-in-redeemer-value', '""',
            '--tx-in-script-file', smartcontract_path
        ]
        tx.build_tx(log, cache, watch_addr, until_tip, contract_utxo_in, utxo_col, tx_out, tx_data)
        
        witnesses = [
            '--signing-key-file',
            watch_skey_path
        ]
        tx.sign_tx(log, cache, witnesses)
        tx.submit_tx(log, cache)
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nNo collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.\n')
            runlog.close()
        exit(0)

def start_deposit(log, cache, watch_addr, watch_skey_path, watch_vkey_path, watch_key_hash, smartcontract_path, token_policy_id, token_name, collateral):
    # Begin log file
    runlog_file = log + 'run.log'

    smartcontract_addr = tx.get_smartcontract_addr(smartcontract_path)

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
    DATUM_HASH  = tx.get_hash_value('"{}"'.format(FINGERPRINT)).replace('\n', '')
    #print('Datum Hash: ', DATUM_HASH)
    deposit(log, cache, watch_addr, watch_skey_path, smartcontract_addr, token_policy_id, token_name, deposit_amt, sc_ada_amt, ada_amt, DATUM_HASH, collateral)

def create_smartcontract(src, pubkeyhash, price):
    # Replace the validator options
    template_src = src + 'src/' + 'template_SwapNFT.hs'
    output_src = src + 'src/' + 'SwapNFT.hs'
    with open(template_src, 'r') as smartcontract :
        scdata = smartcontract.read()
        smartcontract.close()
    scdata = scdata.replace(str(pubkeyhash), 'PUBKEY_HASH010101010101010101010101010101010101010101010')
    scdata = scdata.replace(int(price), '00000000000000')
    with open(output_src, 'w') as smartcontract:
        smartcontract.write(scdata)
        smartcontract.close()
    
    # Compile the plutus smartcontract
    data = subprocess.Popen(['cabal', 'build'], stdout = subprocess.PIPE)
    output = data.communicate()
    print("output: ",output)
    data = subprocess.Popen(['cabal', 'run'], stdout = subprocess.PIPE)
    output = data.communicate()

    # Move the plutus file to the working directory
    os.replace(src + 'swaptoken.plutus', 'swaptoken.plutus')

def setup(log, cache, reconfig=False):
    if reconfig:
        print('\nWARNING: Your current profile data is about to be overwritten! Exit now if you do not want to do that.\n\n')
    print("\nSetting up a new profile!\n\n*NOTE*\nThis will generate a profile.json file which is saved in your main app working folder.\n\n")
    NETWORKINPUT = input("\nNetwork Type (simply enter either mainnet or testnet)\nNetwork:")
    if NETWORKINPUT == 'testnet':
        MAGICINPUT = input("\nTestnet Magic Number:")
    CLI_PATH = input("\nPath to cardano-cli (or simply enter cardano-cli if it's set in your path)\nCardano-CLI Path:")
    API_ID = input("\nBlockfrost API ID:") # Blockfrost API ID
    WATCH_ADDR = input("\nWatched Wallet Address:") # Wallet address of wallet to monitor for incoming payments
    COLLATSTRING = input("\nCollateral Lovelace Amount (usually 2000000)\nCollateral in Lovelace:") # Should be min of 2000000 lovelace in a separate UTxO in buyer's wallet
    CHECKSTRING = input("\nCheck for Transactions Between Payment Processing (False is recommended & run another instance with get_transactions param set)\nType True or False:")
    WLUSESTRING = input("\nUse a Whitelist (Must have whitelist.txt in same folder as this app)\nType True or False:")
    WLONESTRING = input("\nRemove from Whitelist After 1 Payment is Received\nType True or False:")
    WATCH_SKEY_PATH = input("\nWatched Wallet skey File Path (e.g. /home/user/wallets/watch.skey)\nWatched Wallet skey Path:")
    WATCH_VKEY_PATH = input("\nPath to Watched Wallet Verification Key File (eg /home/user/node/wallet/payment.vkey)\nPath to vkey File:>")
    WATCH_KEY_HASH = tx.get_address_pubkeyhash(WATCH_VKEY_PATH)
    SMARTCONTRACT_PATH = input("\nSmartContract File Path (e.g. /home/user/smartcontracts/swap.plutus OR leave blank to use the built-in simple token swap contract)\nSmartContract Path:")
    if len(SMARTCONTRACT_PATH) == 0:
        approot = os.path.realpath(os.path.dirname(__file__))
        SMARTCONTRACT_PATH = os.path.join(approot, 'swaptoken.plutus')
    TOKEN_POLICY_ID = input("\nToken Policy ID (the long string before the dot)\nToken Policy ID:")
    TOKEN_NAME = input("\nToken Name (comes after the dot after the policy ID)\nToken Name:")
    EXPECT_ADA = input("\nLovelace amount to expect and watch for\nLovelace Amount:")
    PRICE = input("\nLovelace price, if any, that should be paid along with a smart contract transaction back to your watch wallet\nLovelace Price:")
    TOKEN_QTY = input("\nToken quantity amount to give in each swap out\nToken per-tx Amount:")
    RETURN_ADA = input("\nLovelace amount to return with the token transfer (cannot be below protocol limit)\nReturn Lovelace:")
    RECIPIENT_ADDR = input("\nSingle Recipient Wallet Address to expect payment from (only set this if no whitelist is being used)\nRecipient Addr:")
    NETWORK = 'mainnet'
    MAGIC = ''
    BLOCKFROST = 'mainnet'
    if NETWORKINPUT == 'testnet':
        NETWORK = 'testnet-magic'
        MAGIC = MAGICINPUT
        BLOCKFROST = NETWORKINPUT
    COLLATERAL = int(COLLATSTRING)
    CHECK = False
    USE_WHITELIST = False
    WHITELIST_ONCE = False
    if CHECKSTRING == 'True':
        CHECK = True
    if WLUSESTRING == 'True':
        USE_WHITELIST = True
    if WLONESTRING == 'True':
        WHITELIST_ONCE = True

    rawSettings = {'network':NETWORK,'magic':MAGIC,'cli_path':CLI_PATH,'blockfrost':BLOCKFROST,'api':API_ID,'watchaddr':WATCH_ADDR,'collateral':COLLATERAL,'check':CHECK,'wluse':USE_WHITELIST,'wlone':WHITELIST_ONCE,'watchskey':WATCH_SKEY_PATH,'watchvkey':WATCH_VKEY_PATH,'watchkeyhash':WATCH_KEY_HASH,'scpath':SMARTCONTRACT_PATH,'tokenid':TOKEN_POLICY_ID,'tokenname':TOKEN_NAME,'expectada':EXPECT_ADA,'price':PRICE,'tokenqty':TOKEN_QTY,'returnada':RETURN_ADA,'recipient':RECIPIENT_ADDR}

    jsonSettings = json.dumps(rawSettings)

    settings_file = 'profile.json'
    is_set_file = os.path.isfile(settings_file)
    with open(settings_file, 'w') as runlog:
        runlog.write(jsonSettings)
        runlog.close()
    
    print('\nProfile Saved! Exiting . . . ')
    exit(0)


if __name__ == "__main__":
    # Setup Temp Directory (try to)
    scptroot = os.path.realpath(os.path.dirname(__file__))
    SRC = os.path.join(os.path.join(scptroot, 'smartcontract-src'), '')
    logname = 'logs'
    logpath = os.path.join(scptroot, logname)
    LOG = os.path.join(logpath, '')
    cachename = 'cache'
    cachepath = os.path.join(scptroot, logname + '/' + cachename)
    CACHE = os.path.join(cachepath, '')

    try:
        os.mkdir(logname)
        os.chdir(logname)
        os.mkdir(cachename)
    except OSError:
        pass

    runlog_file = LOG + 'run.log'
    is_runlog_file = os.path.isfile(runlog_file)
    if not is_runlog_file:
        try:
            open(runlog_file, 'x')
        except OSError:
            pass
    with open(runlog_file, 'a') as runlog:
        time_now = datetime.datetime.now()
        runlog.write('\nNew Run at: ' + str(time_now))
        runlog.close()
    
    # Setup Settings Dictionary
    settings_file = 'profile.json'
    is_settings_file = os.path.isfile(settings_file)
    if not is_settings_file:
        try:
            open(settings_file, 'x')
            setup(LOG, CACHE)
        except OSError:
            pass
    
    # Input for setup
    if len(argv) > 1:
        INPUT = argv[1]
        if INPUT == 'reconfigure':
            setup(LOG, CACHE, True)

    # Load settings
    PROFILE = json.load(open(settings_file, 'r'))

    API_ID = PROFILE['api']
    WATCH_ADDR = PROFILE['watchaddr']
    COLLATERAL = PROFILE['collateral']
    CHECK = PROFILE['check']
    USE_WHITELIST = PROFILE['wluse']
    WHITELIST_ONCE = PROFILE['wlone']
    WATCH_SKEY_PATH = PROFILE['watchskey']
    WATCH_VKEY_PATH = PROFILE['watchvkey']
    WATCH_KEY_HASH = PROFILE['watchkeyhash']
    SMARTCONTRACT_PATH = PROFILE['scpath']
    TOKEN_POLICY_ID = PROFILE['tokenid']
    TOKEN_NAME = PROFILE['tokenname']
    EXPECT_ADA = PROFILE['expectada']
    PRICE = PROFILE['price']
    TOKEN_QTY = PROFILE['tokenqty']
    RETURN_ADA = PROFILE['returnada']
    RECIPIENT_ADDR = PROFILE['recipient']

    # Check for smartcontract file and prompt to create if not found
    sc_file = SMARTCONTRACT_PATH
    is_sc_file = os.path.isfile(sc_file)
    if not is_sc_file:
        create_smartcontract(SRC, WATCH_KEY_HASH, PRICE)

    # Check for watched wallet signing key file
    if isfile(WATCH_SKEY_PATH) is False:
        print('The file:', WATCH_SKEY_PATH, 'could not be found.')
        exit(0)

    if len(argv) > 1 and len(API_ID) > 1 and len(WATCH_ADDR) > 1:
        INPUT = argv[1]

        if INPUT == 'create_smartcontract':
            create_smartcontract(SRC, WATCH_KEY_HASH, PRICE)

        if INPUT == 'get_transactions':
            while True:
                result_tx = tx.log_new_txs(LOG, API_ID, WATCH_ADDR)
                time.sleep(5)

        if INPUT == 'deposit':
            start_deposit(LOG, CACHE, WATCH_ADDR, WATCH_SKEY_PATH, WATCH_VKEY_PATH, WATCH_KEY_HASH, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, COLLATERAL)

    # Calculate the "fingerprint" and finalize other variables
    FINGERPRINT = tx.get_token_identifier(TOKEN_POLICY_ID, TOKEN_NAME)
    DATUM_HASH  = tx.get_hash_value('"{}"'.format(FINGERPRINT)).replace('\n', '')
    SMARTCONTRACT_ADDR = tx.get_smartcontract_addr(SMARTCONTRACT_PATH)
    
    # Begin loop here
    while True:
        #print("starting loop, waiting a few seconds")
        time.sleep(10)

        # Check for payment, initiate Smart Contract on success
        # Only run payment check if new transactions are recorded
        if CHECK:
            result_tx = tx.log_new_txs(LOG, API_ID, WATCH_ADDR)
            with open(runlog_file, 'a') as runlog:
                runlog.write('New txs to compare: '+str(result_tx)+'\n')
                runlog.close()
            #print("new txs gathered: "+str(result_tx)+"\n")
        
        time.sleep(10)
        result = 'none'

        if USE_WHITELIST:
            whitelist_file = os.path.join(os.path.realpath(os.path.dirname(__file__)), 'whitelist.txt')
            is_whitelist_file = os.path.isfile(whitelist_file)
            if not is_whitelist_file:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('Missing expected file: whitelist_nft.txt in this same folder!\n')
                    runlog.close()
                exit(0)
            whitelist_r = open(whitelist_file, 'r')
            windex = 0
            # Foreach line of the whitelist file
            for waddr in whitelist_r:
                windex += 1
                if not EXPECT_ADA:
                    EXPECT_ADA = 0
                RECIPIENT_ADDR = waddr.strip()
                result = tx.check_for_payment(LOG, API_ID, WATCH_ADDR, EXPECT_ADA, RECIPIENT_ADDR)
                if len(result) < 1:
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('No new payments detected\n')
                        runlog.close()
                    continue
                if WHITELIST_ONCE:
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
                with open(runlog_file, 'a') as runlog:
                    runlog.write('Running whitelist for addr: '+RECIPIENT_ADDR+' | '+str(EXPECT_ADA)+'\n')
                    runlog.close()
                # Run swap on matched tx
                smartcontractswap(LOG, CACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, TOKEN_QTY, RETURN_ADA, PRICE, COLLATERAL)
                time.sleep(300)
            whitelist_r.close()
    
        else:
            if not EXPECT_ADA:
                EXPECT_ADA = 0
            if not RECIPIENT_ADDR:
                RECIPIENT_ADDR = 'none'
            result = tx.check_for_payment(LOG, API_ID, WATCH_ADDR, EXPECT_ADA, RECIPIENT_ADDR)
            if len(result) > 1:
                with open(runlog_file, 'a') as runlog:
                    runlog.write('No new payment transactions detected\n')
                    runlog.close()
                exit(0)
            for line in result.splitlines():
                cells = line.split(',')
                tx_addr = cells[1]
                tx_amnt = int(cells[2])
                if EXPECT_ADA != 0:
                    if EXPECT_ADA != tx_amnt:
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('Error! Expected ADA and returned ADA tx do not match (line 349)\n')
                            runlog.close()
                        exit(0)
                else:
                    EXPECT_ADA = tx_amnt
                if RECIPIENT_ADDR != 'none':
                    if RECIPIENT_ADDR != tx_addr:
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('Error! Address and returned address do not match (line 350)\n')
                            runlog.close()
                        exit(0)
                else:
                    RECIPIENT_ADDR = tx_addr
                with open(runlog_file, 'a') as runlog:
                    runlog.write('Performing non-whitelist/normal run for: '+tx_addr+' | '+str(tx_amnt)+'\n')
                    runlog.close()
                smartcontractswap(LOG, CACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, TOKEN_QTY, RETURN_ADA, PRICE, COLLATERAL)
                time.sleep(300)
