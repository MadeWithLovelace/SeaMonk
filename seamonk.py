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
from threading import Timer

class runTimed(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.next_call = time.time()
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self.next_call += self.interval
            self._timer = Timer(self.next_call - time.time(), self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False

def inputp(prompt, text):
    def hook():
        readline.insert_text(text)
        readline.redisplay()
    readline.set_pre_input_hook(hook)
    result = input(prompt)
    readline.set_pre_input_hook()
    return result
    
def deposit(profile_name, log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, deposit_amt, sc_ada_amt, ada_amt, datum_hash, check_price, collateral, filePre, tokens_to_swap = 0, recipient_addr = '', replenish = False):
    # Begin log file
    runlog_file = log + 'run.log'
    
    # Clear the cache
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
        tx_out = tx.process_tokens(profile_name, tokens, watch_addr, 'all', ada_amt) # Process all tokens and change
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
        tx.submit_tx(profile_name, filePreCollat)
        tx_hash_collat = tx.get_tx_hash(profile_name, filePreCollat)
        if not replenish:
            print('\nWaiting for new UTxO to appear on blockchain...')
        
        # Wait for tx to appear
        tx_hash_collat = tx_hash_collat.strip()
        tx_collat_flag = False
        while not tx_collat_flag:
            sleep(5)
            tx_collat_flag = tx.check_for_tx(profile_name, tx_hash_collat)
    
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
        tx_out = tx.process_tokens(profile_name, tokens, watch_addr, 'all', ada_amt, [token_policy_id, token_name]) # Account for all except token to swap
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # UTxO to replenish collateral
        if tok_new > 0:
            tx_out += tx.process_tokens(profile_name, tokens, watch_addr, tok_new, ada_amt) # Account for deposited-token change (if any)
        if tokens_to_swap > 0:
            tx_out += tx.process_tokens(profile_name, tokens, recipient_addr, tokens_to_swap, ada_amt, [token_policy_id, token_name], False) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(profile_name, tokens, smartcontract_addr, sc_out, sc_ada_amt, [token_policy_id, token_name], False) # Send just the token for swap
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
                    sc_out_tk = sc_tokens[token][t_qty]

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
        tx.submit_tx(profile_name, filePre)
        tx_hash = tx.get_tx_hash(profile_name, filePre)
        return tx_hash
    else:
        if not replenish:
            print('\nCollateral UTxO missing or couldn\'t be created! Exiting...\n')
            exit(0)
        return 'Error: Collateral UTxO Missing or could not be created.'

def withdraw(profile_name, log, cache, watch_addr, watch_skey_path, smartcontract_addr, smartcontract_path, token_policy_id, token_name, datum_hash, recipient_addr, return_ada, price, collateral, filePre, refund_amnt = 0):
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
        
        tx_out = tx.process_tokens(profile_name, tokens, watch_addr) # Change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if refund_amnt > 0:
            tx_out += ['--tx-out', recipient_addr + '+' + str(refund_amnt)] # UTxO to Refund
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
                    sc_out = sc_tokens[token][t_qty]
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
        tx.submit_tx(profile_name, filePre)
        tx_hash = tx.get_tx_hash(profile_name, filePre)
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
        tx_out = tx.process_tokens(profile_name, sc_tokens, recipient_addr, sc_out, return_ada) # UTxO to Send Token(s) to the Buyer
        tx_out += tx.process_tokens(profile_name, tokens, watch_addr) # Change
        tx_out += ['--tx-out', watch_addr + '+' + str(collateral)] # Replenish collateral
        if price:
            tx_out += ['--tx-out', watch_addr + '+' + str(price)] # UTxO for price if set to process price payment
        if sc_new > 0:
            tx_out += tx.process_tokens(profile_name, sc_tokens, smartcontract_addr, sc_new) # UTxO to Send Change to Script - MUST BE LAST UTXO FOR DATUM
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
        tx.submit_tx(profile_name, filePre)
        tx_hash = tx.get_tx_hash(profile_name, filePre)
    else:
        with open(runlog_file, 'a') as runlog:
            runlog.write('\nNo collateral UTxO found! Please create a UTxO of 2 ADA (2000000 lovelace) before trying again.\n')
            runlog.close()
        tx_hash = 'error'
    return tx_hash

def start_deposit(profile_name, log, cache, watch_addr, watch_skey_path, watch_vkey_path, watch_key_hash, smartcontract_path, token_policy_id, token_name, check_price, collateral):
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
    tx_hash = tx_hash.strip()
    tx_flag = False
    while not tx_flag:
        sleep(5)
        tx_flag = tx.check_for_tx(profile_name, tx_hash)
    print('\nDeposit Completed!')

def create_smartcontract(profile_name, sc_path, src, pubkeyhash, price):
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
    sc_addr = tx.get_smartcontract_addr(profile_name, sc_path)
    print('\n================ Finished! ================\n > Your SmartContract Address For Your Records Is: ' + sc_addr + '\n\n')
    exit(0)

def setup(logroot, profile_name='', reconfig=False, append=False):
    NETWORK_INPUT = ''
    MAGIC_INPUT = ''
    CLI_PATH_INPUT = ''
    API_ID_INPUT = ''
    WATCH_ADDR_INPUT = ''
    COLLATERAL_INPUT = ''
    CHECK_INPUT = ''
    WLENABLED_INPUT = ''
    WHITELIST_ONCE_INPUT = ''
    WATCH_SKEY_PATH_INPUT = ''
    WATCH_VKEY_PATH_INPUT = ''
    WATCH_KEY_HASH_INPUT = ''
    SMARTCONTRACT_PATH_INPUT = ''
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
    if reconfig:
        settings_file = 'profile.json'
        # Load settings
        load_profile = json.load(open(settings_file, 'r'))
        if len(profile_name) == 0:
            profile_name = list(load_profile.keys())[0]
        PROFILE = load_profile[profile_name]
        NETWORK_INPUT = PROFILE['network']
        if NETWORK_INPUT == 'testnet-magic':
            NETWORK_INPUT = 'testnet'
        MAGIC_INPUT = PROFILE['magic']
        CLI_PATH_INPUT = PROFILE['cli_path']
        API_ID_INPUT = PROFILE['api']
        WATCH_ADDR_INPUT = PROFILE['watchaddr']
        COLLATERAL_INPUT = PROFILE['collateral']
        CHECK_INPUT = PROFILE['check']
        WLENABLED_INPUT = PROFILE['wlenabled']
        WHITELIST_ONCE_INPUT = PROFILE['wlone']
        WATCH_SKEY_PATH_INPUT = PROFILE['watchskey']
        WATCH_VKEY_PATH_INPUT = PROFILE['watchvkey']
        WATCH_KEY_HASH_INPUT = PROFILE['watchkeyhash']
        SMARTCONTRACT_PATH_INPUT = PROFILE['scpath']
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
    print('\n*IMPORTANT NOTES*\n')
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
    if not reconfig:
        UNIQUE_NAME = input('\nEnter A Unique Profile Name For This Profile\n(no spaces, e.g. CypherMonk_NFT_Sale)\n >Unique Name:')
    NETWORKINPUT = inputp('\nNetwork Type (enter either mainnet or testnet)\n >Network Type:', NETWORK_INPUT)
    if NETWORKINPUT == 'testnet':
        MAGICINPUT = inputp(' >Testnet Magic:', MAGIC_INPUT)
    CLI_PATH = inputp('\nExplicit Path To "cardano-cli"\n(leave empty if cardano-cli is in your system path and\nit is the version you want to use with this profile)\n >Cardano-CLI Path:', CLI_PATH_INPUT)
    API_ID = inputp('\nYour Blockfrost API ID\n(should match the network-specific ID i.e. mainnet vs testnet)\n >Blockfrost API ID:', API_ID_INPUT)
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
    CHECKSTRING = inputp('\nCheck for Transactions Simultaneously?\n(Recommended: True - if set to false you will need to run a seperate instance of seamonk.py with the option "get_transactions" for getting transactions)\n >Enter True or False:', str(CHECK_INPUT))
    WLENABLEDSTRING = inputp('\nUse a whitelist?\n(if false, any payment received to the watched address will be checked for matching amount params)\n >Enter True or False:', str(WLENABLED_INPUT))
    if WLENABLEDSTRING == 'True' or WLENABLEDSTRING == 'true':
        WLONESTRING = inputp('\nRemove A Sender Address From Whitelist After 1 Payment is Received?\n >Enter True or False:', str(WHITELIST_ONCE_INPUT))
    print('\n\nAfter this setup and any smart-contract generating, you will need to deposit into the smart contract by running: "python3 seamonk.py --option deposit". The following inputs are related to deposits. For auto-replenishing a smart-contract wherein you are sending a large amount to be processed in smaller batches, the token quantity you enter in the following input, will apply to each deposit replenish attempt.\n\n')
    DEPOSIT_AMNT = inputp('\nQuantity of Tokens You Will Deposit\n(you can enter a batch amount, when it runs low the app will try to replenish with the same batch amount)\n >Quantity of ' + TOKEN_NAME +' Tokens to Deposit:', DEPOSIT_AMNT_INPUT)
    RECURRINGSTRING = inputp('\nIs This A Recurring Amount?\n(type True or False)\n >Recurring Deposit? ', str(RECURRINGSTRING_INPUT))
    SC_ADA_AMNT = inputp('\nAmount Of Lovelace To Be At UTxO On SmartContract\n(cannot be lower than protocol, 2 ADA is recommended for most cases)\n >Amount in Lovelace:', SC_ADA_AMNT_INPUT)
    WT_ADA_AMNT = inputp('\nAmount Of Lovelace To Be At UTxO Of Token Change At Watched Wallet\n(cannot be lower than protocol, 2 ADA is recommended for most cases)\n >Amount in Lovelace:', WT_ADA_AMNT_INPUT)
    AUTO_REFUNDSTRING = inputp('\nAutomatically Refund Payments Too Large?\n(type True or False - this will enable auto-refunds for payments which exceed the tokens ever available for swap by the SmartContract)\n >Refunds Enabled?', str(AUTO_REFUND_INPUT))
    FEE_CHARGEINPUT = inputp('\nFee To Charge For Refunds\n(rather than simply deducting a protocol fee, setting a higher fee discourages abuse and more attentive participation..if left blank default is 500000 lovelace)\n >Fee Charged For Refunds in Lovelace:', str(FEE_CHARGE_INPUT))
    
    # Setup profile-specific cache and log folders
    log = os.path.join(os.path.join(logroot, UNIQUE_NAME), '')
    cache = os.path.join(os.path.join(log, 'cache'), '')
    txlog = os.path.join(os.path.join(log, 'txs'), '')
    try:
        os.mkdir(log)
        os.mkdir(cache)
        os.mkdir(txlog)
    except OSError:
        pass

    # Process inputs
    if len(CLI_PATH) == 0:
        CLI_PATH = 'cardano-cli'
    WATCH_KEY_HASH = tx.get_address_pubkeyhash(CLI_PATH, WATCH_VKEY_PATH)
    if len(SMARTCONTRACT_PATH) == 0:
        SMARTCONTRACT_PATH = log + UNIQUE_NAME + '.plutus'
    NETWORK = 'mainnet'
    MAGIC = ''
    API_URI = 'https://cardano-' + NETWORKINPUT + '.blockfrost.io/api/v0/'
    if NETWORKINPUT == 'testnet':
        NETWORK = 'testnet-magic'
        MAGIC = MAGICINPUT
    COLLATERAL = int(COLLATSTRING)
    MIN_WATCH = int(MININPUT)
    if not FEE_CHARGEINPUT:
        FEE_CHARGEINPUT = "500000"
    FEE_CHARGE = int(FEE_CHARGEINPUT)
    CHECK = False
    WLENABLED = False
    WHITELIST_ONCE = False
    RECURRING = False
    AUTO_REFUND = False
    if CHECKSTRING == 'True' or CHECKSTRING == 'true':
        CHECK = True
    if WLENABLEDSTRING == 'True' or WLENABLEDSTRING == 'true':
        WLENABLED = True
    if WLONESTRING == 'True' or WLONESTRING == 'true':
        WHITELIST_ONCE = True
    if RECURRINGSTRING == 'True' or RECURRINGSTRING == 'true':
        RECURRING = True
    if AUTO_REFUNDSTRING == 'True' or AUTO_REFUNDSTRING == 'true':
        AUTO_REFUND = True

    # Save to dictionary
    rawSettings = {'log':log,'cache':cache,'txlog':txlog,'network':NETWORK,'magic':MAGIC,'cli_path':CLI_PATH,'api_uri':API_URI,'api':API_ID,'watchaddr':WATCH_ADDR,'collateral':COLLATERAL,'check':CHECK,'wlenabled':WLENABLED,'wlone':WHITELIST_ONCE,'watchskey':WATCH_SKEY_PATH,'watchvkey':WATCH_VKEY_PATH,'watchkeyhash':WATCH_KEY_HASH,'scpath':SMARTCONTRACT_PATH,'tokenid':TOKEN_POLICY_ID,'tokenname':TOKEN_NAME,'expectada':EXPECT_ADA,'min_watch':MIN_WATCH,'price':PRICE,'tokenqty':TOKEN_QTY,'returnada':RETURN_ADA,'deposit_amnt':DEPOSIT_AMNT,'recurring':RECURRING,'sc_ada_amnt':SC_ADA_AMNT,'wt_ada_amnt':WT_ADA_AMNT, 'auto_refund':AUTO_REFUND, 'fee_to_charge':FEE_CHARGE}

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

if __name__ == "__main__":
    # Set default program mode to running = True
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
    SRC = os.path.join(os.path.join(scptroot, 'smartcontract-src'), '')

    logname = 'profiles'
    logpath = os.path.join(scptroot, logname)
    LOGROOT = os.path.join(logpath, '')

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
    COLLATERAL = PROFILE['collateral']
    CHECK = PROFILE['check']
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

    # Input before settings load
    if len(OPTION_PASSED) > 0:
        if OPTION_PASSED == 'reconfigure':
            setup(LOGROOT, PROFILE_NAME, True)
        if OPTION_PASSED == 'new_profile':
            setup(LOGROOT, PROFILE_NAME, False, True)

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
        runlog.write('\n===============================\n          New Run at: ' + time_now + '\n===============================\n')
        runlog.close()

    # Check for smartcontract file and prompt to create if not found
    sc_file = SMARTCONTRACT_PATH
    is_sc_file = os.path.isfile(sc_file)
    if not is_sc_file:
        create_smartcontract(PROFILE_NAME, SMARTCONTRACT_PATH, SRC, WATCH_KEY_HASH, PRICE)

    # Check for watched wallet signing key file
    if isfile(WATCH_SKEY_PATH) is False:
        print('The file:', WATCH_SKEY_PATH, 'could not be found.')
        exit(0)

    if len(OPTION_PASSED) > 1 and len(API_ID) > 1 and len(WATCH_ADDR) > 1:
        if OPTION_PASSED == 'create_smartcontract':
            create_smartcontract(PROFILE_NAME, SMARTCONTRACT_PATH, SRC, WATCH_KEY_HASH, PRICE)

        if OPTION_PASSED == 'get_transactions':
            running = False

        if OPTION_PASSED == 'deposit':
            CHECK_PRICE = 0
            if EXPECT_ADA != PRICE:
                CHECK_PRICE = int(PRICE)
                print('\nTo check if price amount in wallet: ' + str(CHECK_PRICE))
            start_deposit(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, WATCH_VKEY_PATH, WATCH_KEY_HASH, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, CHECK_PRICE, COLLATERAL)
        
        if OPTION_PASSED == 'replenish':
            # May be unneeded
            print('\nOption not yet enabled')
            exit(0)

    # Calculate the "fingerprint" and finalize other variables
    FINGERPRINT = tx.get_token_identifier(TOKEN_POLICY_ID, TOKEN_NAME)
    DATUM_HASH  = tx.get_hash_value(PROFILE_NAME, '"{}"'.format(FINGERPRINT)).replace('\n', '')
    SMARTCONTRACT_ADDR = tx.get_smartcontract_addr(PROFILE_NAME, SMARTCONTRACT_PATH)
    
    # TESTING
    """
    print("profile loaded: " + PROFILE_NAME)
    print("profile settings loaded: log=" + PROFILELOG + " | cache=" + PROFILECACHE + " | api_id=" + API_ID + " | watch_addr=" + WATCH_ADDR + " | collateral=" + str(COLLATERAL) + " | check=" + str(CHECK) + " | whitelist_once=" + str(WHITELIST_ONCE) + " | skey=" + WATCH_SKEY_PATH + " | vkey=" + WATCH_VKEY_PATH + " | pubkey_hash="+WATCH_KEY_HASH+" | sc_path=" + SMARTCONTRACT_PATH + " | token_id=" + TOKEN_POLICY_ID + " | token_name=" + TOKEN_NAME + " | watch_for=" + EXPECT_ADA + " | min_watch=" + MIN_WATCH + " | price=" + PRICE + " | token_qty=" + TOKEN_QTY+ " | return_ada=" + RETURN_ADA)
    print("Additional settings:")
    print(load_profile[PROFILE_NAME]['cli_path'])
    print(load_profile[PROFILE_NAME]['network'])
    print(load_profile[PROFILE_NAME]['magic'])
    print(load_profile[PROFILE_NAME]['api_uri'])
    exit(0)
    """
    # END

    # Start get_transactions thread
    if CHECK or running == False:
        runTimed(2, tx.log_new_txs, PROFILE_NAME, API_ID, WATCH_ADDR)

    # Begin main payment checking/recording loop here
    while running:
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
            result = tx.check_for_payment(PROFILE_NAME, API_ID, WATCH_ADDR, EXPECT_ADA, MIN_WATCH, RECIPIENT_ADDR)
            if len(result) < 1:
                continue
            RESLIST = result.split(',')
            RECIPIENT_ADDR = RESLIST[1]
            ADA_RECVD = int(RESLIST[2])
            with open(runlog_file, 'a') as runlog:
                runlog.write('\n===== Matching TX: '+str(result)+' =====')
                runlog.close()
            if MIN_WATCH > 0:
                RET_INT = int(RETURN_ADA)
                ADA_TOSWAP = ADA_RECVD - RET_INT
                TOKENS_TOSWAP = int((int(TOKEN_QTY) * ADA_TOSWAP) / 1000000)
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nRunning whitelist for addr/ada-rec/tokens-to-swap: '+RECIPIENT_ADDR+' | '+str(ADA_RECVD)+' | '+str(TOKENS_TOSWAP)+'')
                runlog.close()
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
                            runlog.write('\nRefunding: '+str(REFUND_AMNT))
                            runlog.close()
                        filePre = 'refundTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
                        tx_refund_a_hash = withdraw(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, RETURN_ADA, PRICE, COLLATERAL, filePre, REFUND_AMNT)

                        # Check for tx to complete
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nWaiting for tx to clear, with hash: '+tx_refund_a_hash.strip())
                            runlog.close()
                        tx_refund_a_hash = tx_refund_a_hash.strip()
                        tx_refund_a_flag = False
                        while not tx_refund_a_flag:
                            sleep(5)
                            tx_refund_a_flag = tx.check_for_tx(PROFILE_NAME, tx_refund_a_hash)

                        # Record the payment as completed, leave whitelist untouched since not a valid swap tx
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nHash found, TX completed. Writing to payments.log...')
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

                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nTX Result: '+tx_rsc_hash+' - Waiting for confirmation...')
                        runlog.close()

                    # Wait for transaction to clear...
                    tx_rsc_hash = tx_rsc_hash.strip()
                    tx_rsc_flag = False
                    while not tx_rsc_flag:
                        sleep(5)
                        tx_rsc_flag = tx.check_for_tx(PROFILE_NAME, tx_rsc_hash)
                    with open(runlog_file, 'a') as runlog:
                        runlog.write('\nReplenish-SC TX Hash Found: '+tx_rsc_hash)
                        runlog.close()

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

                        # Wait for transaction to clear...
                        tx_refund_b_hash = tx_refund_b_hash.strip()
                        tx_refund_b_flag = False
                        while not tx_refund_b_flag:
                            sleep(5)
                            tx_refund_b_flag = tx.check_for_tx(PROFILE_NAME, tx_refund_b_hash)
                        with open(runlog_file, 'a') as runlog:
                            runlog.write('\nRefund TX Hash Found: '+tx_refund_b_hash)
                            runlog.close()
                        
                    # Record the payment as completed
                    payments_file = PROFILELOG + 'payments.log'
                    with open(payments_file, 'a') as payments_a:
                        payments_a.write(result + '\n')
                        payments_a.close()
                    sleep(5)
                    continue

            # Run swap on matched tx
            with open(runlog_file, 'a') as runlog:
                runlog.write('\nProcess this TX Swap: '+RECIPIENT_ADDR+' | tokens:'+str(TOKENS_TOSWAP)+' | ada:'+str(ADA_RECVD))
                runlog.close()
            filePre = 'swapTO' + RECIPIENT_ADDR + '_' + strftime("%Y-%m-%d_%H-%M-%S", gmtime()) + '_'
            tx_sc_hash = smartcontractswap(PROFILE_NAME, PROFILELOG, PROFILECACHE, WATCH_ADDR, WATCH_SKEY_PATH, SMARTCONTRACT_ADDR, SMARTCONTRACT_PATH, TOKEN_POLICY_ID, TOKEN_NAME, DATUM_HASH, RECIPIENT_ADDR, str(TOKENS_TOSWAP), RETURN_ADA, PRICE, COLLATERAL, filePre)
            if tx_sc_hash != 'error':
                # Wait for swap to clear...
                tx_sc_hash = tx_sc_hash.strip()
                tx_sc_flag = False
                while not tx_sc_flag:
                    sleep(5)
                    tx_sc_flag = tx.check_for_tx(PROFILE_NAME, tx_sc_hash)
                with open(runlog_file, 'a') as runlog:
                    runlog.write('\nSmartContract Swap TX Hash Found: '+tx_sc_hash)
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
                    runlog.write('\nSC Swap Failed: '+RECIPIENT_ADDR+' | '+str(TOKENS_TOSWAP)+' | '+str(ADA_RECVD))
                    runlog.close()
        whitelist_r.close()