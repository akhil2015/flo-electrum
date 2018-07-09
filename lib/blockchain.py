# Electrum - lightweight Bitcoin client
# Copyright (C) 2012 thomasv@ecdsa.org
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import os
import threading

from . import util
from . import bitcoin
from .bitcoin import *
import time

try:
    import scrypt
    getPoWHash = lambda x: scrypt.hash(x, x, N=1024, r=1, p=1, buflen=32)
except ImportError:
    util.print_msg("Warning: package scrypt not available; synchronization could be very slow")
    from .scrypt import scrypt_1024_1_1_80 as getPoWHash
# FLO Constants
MAX_TARGET = 0x00000fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
nPowTargetSpacing = 40   # 40s block time
# V1
nTargetTimespan_Version1 = 60 * 60
nInterval_Version1 = nTargetTimespan_Version1 / nPowTargetSpacing
nMaxAdjustUp_Version1 = 75
nMaxAdjustDown_Version1 = 300
nAveragingInterval_Version1 = nInterval_Version1
# V2
nHeight_Difficulty_Version2 = 208440
nInterval_Version2 = 15
nMaxAdjustDown_Version2 = 300
nMaxAdjustUp_Version2 = 75
nAveragingInterval_Version2 = nInterval_Version2
# V3
nHeight_Difficulty_Version3 = 426000
nInterval_Version3 = 1
nMaxAdjustDown_Version3 = 3
nMaxAdjustUp_Version3 = 2
nAveragingInterval_Version3 = 6

def serialize_header(res):
    s = int_to_hex(res.get('version'), 4) \
        + rev_hex(res.get('prev_block_hash')) \
        + rev_hex(res.get('merkle_root')) \
        + int_to_hex(int(res.get('timestamp')), 4) \
        + int_to_hex(int(res.get('bits')), 4) \
        + int_to_hex(int(res.get('nonce')), 4)
    return s

def deserialize_header(s, height):
    hex_to_int = lambda s: int('0x' + bh2u(s[::-1]), 16)
    h = {}
    h['version'] = hex_to_int(s[0:4])
    h['prev_block_hash'] = hash_encode(s[4:36])
    h['merkle_root'] = hash_encode(s[36:68])
    h['timestamp'] = hex_to_int(s[68:72])
    h['bits'] = hex_to_int(s[72:76])
    h['nonce'] = hex_to_int(s[76:80])
    h['block_height'] = height
    return h

def hash_header(header):
    if header is None:
        return '0' * 64
    if header.get('prev_block_hash') is None:
        header['prev_block_hash'] = '00'*32
    return hash_encode(Hash(bfh(serialize_header(header))))


def pow_hash_header(header):
    return hash_encode(getPoWHash(bfh(serialize_header(header))))
blockchains = {}

def read_blockchains(config):
    blockchains[0] = Blockchain(config, 0, None)
    fdir = os.path.join(util.get_headers_dir(config), 'forks')
    if not os.path.exists(fdir):
        os.mkdir(fdir)
    l = filter(lambda x: x.startswith('fork_'), os.listdir(fdir))
    l = sorted(l, key = lambda x: int(x.split('_')[1]))
    for filename in l:
        checkpoint = int(filename.split('_')[2])
        parent_id = int(filename.split('_')[1])
        b = Blockchain(config, checkpoint, parent_id)
        h = b.read_header(b.checkpoint)
        if b.parent().can_connect(h, check_height=False):
            blockchains[b.checkpoint] = b
        else:
            util.print_error("cannot connect", filename)
    return blockchains

def check_header(header):
    if type(header) is not dict:
        return False
    for b in blockchains.values():
        if b.check_header(header):
            return b
    return False

def can_connect(header):
    for b in blockchains.values():
        if b.can_connect(header):
            return b
    return False


class Blockchain(util.PrintError):
    """
    Manages blockchain headers and their verification
    """

    def __init__(self, config, checkpoint, parent_id):
        self.config = config
        self.catch_up = None # interface catching up
        self.checkpoint = checkpoint
        self.checkpoints = bitcoin.NetworkConstants.CHECKPOINTS
        self.parent_id = parent_id
        self.lock = threading.Lock()
        with self.lock:
            self.update_size()

    def parent(self):
        return blockchains[self.parent_id]

    def get_max_child(self):
        children = list(filter(lambda y: y.parent_id==self.checkpoint, blockchains.values()))
        return max([x.checkpoint for x in children]) if children else None

    def get_checkpoint(self):
        mc = self.get_max_child()
        return mc if mc is not None else self.checkpoint

    def get_branch_size(self):
        return self.height() - self.get_checkpoint() + 1

    def get_name(self):
        return self.get_hash(self.get_checkpoint()).lstrip('00')[0:10]

    def check_header(self, header):
        header_hash = hash_header(header)
        height = header.get('block_height')
        return header_hash == self.get_hash(height)

    def fork(parent, header):
        checkpoint = header.get('block_height')
        self = Blockchain(parent.config, checkpoint, parent.checkpoint)
        open(self.path(), 'w+').close()
        self.save_header(header)
        return self

    def height(self):
        return self.checkpoint + self.size() - 1

    def size(self):
        with self.lock:
            #print("self._size = " + str(self._size))
            return self._size

    def update_size(self):
        p = self.path()
        self._size = os.path.getsize(p)//80 if os.path.exists(p) else 0

    def verify_header(self, header, prev_hash, target):
        _hash = hash_header(header)
        _powhash = pow_hash_header(header)
        if prev_hash != header.get('prev_block_hash'):
            raise BaseException("prev hash mismatch: %s vs %s" % (prev_hash, header.get('prev_block_hash')))
        if bitcoin.NetworkConstants.TESTNET:
            return
        bits = target
        print("bits calculated: "+str(target))
        temp = header.get('bits')
        print("actual bits: "+str(temp))
        print("I'm inside verify_header")
        if bits != header.get('bits'):
           raise BaseException("bits mismatch: %s vs %s" % (bits, header.get('bits')))
        block_hash=int('0x' + _hash, 16)
        target_val = self.bits_to_target(bits)
        print("target val:"+str(type(target_val)))
        if int('0x' + _powhash, 16) > target_val:
           print("insufficient proof of work: %s vs target %s" % (int('0x' + _hash, 16), target_val))
        print("I passed verify_header(). Calc target values have been matched")

    def verify_chunk(self, index, data):
        num = len(data) // 80
        current_header = (index * 2016)
        #last = (index * 2016 + 2015)
        prev_hash = self.get_hash(current_header - 1)

        for i in range(num):
            print(i)
            start = time.clock()
            target = self.get_target(current_header -1)
            raw_header = data[i*80:(i+1) * 80]
            header = deserialize_header(raw_header, current_header)
            self.verify_header(header, prev_hash, target)
            self.save_chunk_part(header)
            print(time.clock() - start)
            prev_hash = hash_header(header)
            current_header = current_header + 1

    def path(self):
        d = util.get_headers_dir(self.config)
        filename = 'blockchain_headers' if self.parent_id is None else os.path.join('forks', 'fork_%d_%d'%(self.parent_id, self.checkpoint))
        return os.path.join(d, filename)

    def save_chunk_part(self, header):
        filename = self.path()
        delta = header.get('block_height') - self.checkpoint
        data = bfh(serialize_header(header))
        #assert delta == self.size()
        assert len(data) == 80
        self.write(data, delta*80)
        #self.swap_with_parent()

    def save_chunk(self, index, chunk):
        filename = self.path()
        #d = (index * 2016 - self.checkpoint) * 80
        #if d < 0:
        #    chunk = chunk[-d:]
        #    d = 0
        #self.write(chunk, d)
        self.swap_with_parent()

    def swap_with_parent(self):
        if self.parent_id is None:
            return
        parent_branch_size = self.parent().height() - self.checkpoint + 1
        if parent_branch_size >= self.size():
            return
        self.print_error("swap", self.checkpoint, self.parent_id)
        parent_id = self.parent_id
        checkpoint = self.checkpoint
        parent = self.parent()
        with open(self.path(), 'rb') as f:
            my_data = f.read()
        with open(parent.path(), 'rb') as f:
            f.seek((checkpoint - parent.checkpoint)*80)
            parent_data = f.read(parent_branch_size*80)
        self.write(parent_data, 0)
        parent.write(my_data, (checkpoint - parent.checkpoint)*80)
        # store file path
        for b in blockchains.values():
            b.old_path = b.path()
        # swap parameters
        self.parent_id = parent.parent_id; parent.parent_id = parent_id
        self.checkpoint = parent.checkpoint; parent.checkpoint = checkpoint
        self._size = parent._size; parent._size = parent_branch_size
        # move files
        for b in blockchains.values():
            if b in [self, parent]: continue
            if b.old_path != b.path():
                self.print_error("renaming", b.old_path, b.path())
                os.rename(b.old_path, b.path())
        # update pointers
        blockchains[self.checkpoint] = self
        blockchains[parent.checkpoint] = parent

    def write(self, data, offset):
        filename = self.path()
        with self.lock:
            with open(filename, 'r+b') as f:
                if offset != self._size*80:
                    f.seek(offset)
                    f.truncate()
                f.seek(offset)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            self.update_size()

    def save_header(self, header):
        delta = header.get('block_height') - self.checkpoint
        data = bfh(serialize_header(header))
        assert delta == self.size()
        assert len(data) == 80
        self.write(data, delta*80)
        self.swap_with_parent()

    def read_header(self, height):
        assert self.parent_id != self.checkpoint
        if height < 0:
            return
        if height < self.checkpoint:
            return self.parent().read_header(height)
        #print("Height\t= " + str(height))
        #print("self.height()\t= " + str(self.height()))
        if height > self.height():
            return
        delta = height - self.checkpoint
        name = self.path()
        if os.path.exists(name):
            with open(name, 'rb') as f:
                f.seek(delta * 80)
                h = f.read(80)
        if h == bytes([0])*80:
            return None
        return deserialize_header(h, height)

    def get_hash(self, height):
        if height == -1:
            return '0000000000000000000000000000000000000000000000000000000000000000'
        elif height == 0:
            return bitcoin.NetworkConstants.GENESIS
        elif height < len(self.checkpoints) * 2016:
            assert (height+1) % 2016 == 0
            index = height // 2016
            h, t = self.checkpoints[index]
            return h
        else:
            return hash_header(self.read_header(height))

    def AveragingInterval(self, height):
        # V1
        if height < bitcoin.NetworkConstants.nHeight_Difficulty_Version2:
            return bitcoin.NetworkConstants.nAveragingInterval_Version1
        # V2
        elif height < bitcoin.NetworkConstants.nHeight_Difficulty_Version3:
            return bitcoin.NetworkConstants.nAveragingInterval_Version2
        # V3
        else:
            return bitcoin.NetworkConstants.nAveragingInterval_Version3

    def MinActualTimespan(self, height):
        averagingTargetTimespan = self.AveragingInterval(height) * bitcoin.NetworkConstants.nPowTargetSpacing
        # V1
        if height < bitcoin.NetworkConstants.nHeight_Difficulty_Version2:
            return int(averagingTargetTimespan * (100 - bitcoin.NetworkConstants.nMaxAdjustUp_Version1) / 100)
        # V2
        elif height < bitcoin.NetworkConstants.nHeight_Difficulty_Version3:
            return int(averagingTargetTimespan * (100 - bitcoin.NetworkConstants.nMaxAdjustUp_Version2) / 100)
        # V3
        else:
            return int(averagingTargetTimespan * (100 - bitcoin.NetworkConstants.nMaxAdjustUp_Version3) / 100)

    def MaxActualTimespan(self, height):
        averagingTargetTimespan = self.AveragingInterval(height) * bitcoin.NetworkConstants.nPowTargetSpacing
        # V1
        if height < bitcoin.NetworkConstants.nHeight_Difficulty_Version2:
            return int(averagingTargetTimespan * (100 + bitcoin.NetworkConstants.nMaxAdjustDown_Version1) / 100)
        # V2
        elif height < bitcoin.NetworkConstants.nHeight_Difficulty_Version3:
            return int(averagingTargetTimespan * (100 + bitcoin.NetworkConstants.nMaxAdjustDown_Version2) / 100)
        # V3
        else:
            return int(averagingTargetTimespan * (100 + bitcoin.NetworkConstants.nMaxAdjustDown_Version3) / 100)

    def TargetTimespan(self, height):
        # V1
        if height < nHeight_Difficulty_Version2:
            return nTargetTimespan_Version1
        # V2
        if height < nHeight_Difficulty_Version3:
            return nAveragingInterval_Version2 * nPowTargetSpacing
        # V3
        return nAveragingInterval_Version3 * nPowTargetSpacing

    def DifficultyAdjustmentInterval(self, height):
        # V1
        if height < bitcoin.NetworkConstants.nHeight_Difficulty_Version2:
            return bitcoin.NetworkConstants.nInterval_Version1
        # V2
        if height < bitcoin.NetworkConstants.nHeight_Difficulty_Version3:
            return nInterval_Version2
        # V3
        return bitcoin.NetworkConstants.nInterval_Version3

    def get_target(self, index):
        # compute target from chunk x, used in chunk x+1
        if bitcoin.NetworkConstants.TESTNET:
            return 0
        #The range is first 90 blocks because FLO's block time was 90 blocks when it started
        if -1 <= index <= 88:
            return 0x1e0ffff0
        if index < len(self.checkpoints):
            h, t = self.checkpoints[index]
            return t
        # new target
        headerLast = self.read_header(index)
        height = headerLast["block_height"]

        # check if the height passes is in range for retargeting
        if (height + 1) % self.DifficultyAdjustmentInterval(height + 1) != 0:
            return int(headerLast["bits"])

        averagingInterval = self.AveragingInterval(height + 1)
        blockstogoback = averagingInterval - 1
        if (height + 1) != averagingInterval:
            blockstogoback = averagingInterval

        firstHeight = height - blockstogoback
        headerFirst = self.read_header(int(firstHeight))
        firstBlockTime = headerFirst["timestamp"]

        nMinActualTimespan = int(self.MinActualTimespan(int(headerLast["block_height"]) + 1))
        nMaxActualTimespan = int(self.MaxActualTimespan(int(headerLast["block_height"]) + 1))

        # Limit adjustment step
        nActualTimespan = headerLast["timestamp"] - firstBlockTime
        if nActualTimespan < nMinActualTimespan:
            nActualTimespan = nMinActualTimespan
        if nActualTimespan > nMaxActualTimespan:
            nActualTimespan = nMaxActualTimespan

        # Retarget
        bnNewBits = int(headerLast["bits"])
        bnNew = self.bits_to_target(bnNewBits)
        bnOld = bnNew
        # FLO: intermediate uint256 can overflow by 1 bit
        # const arith_uint256 bnPowLimit = UintToArith256(params.powLimit);

        fShift = bnNew > MAX_TARGET - 1
        if (fShift):
            bnNew = bnNew >> 1
        bnNew = bnNew * nActualTimespan
        bnNew = bnNew / self.TargetTimespan(headerLast["block_height"] + 1)
        if fShift:
            bnNew = bnNew << 1

        if bnNew > MAX_TARGET:
            bnNew = MAX_TARGET
        print("bnnew: "+str(bnNew))
        bnNew = self.target_to_bits(int(bnNew))
        return bnNew


    def bits_to_target(self, bits):
        bitsN = (bits >> 24) & 0xff
        if not (bitsN >= 0x03 and bitsN <= 0x1e):
            raise BaseException("First part of bits should be in [0x03, 0x1e]")
        bitsBase = bits & 0xffffff
        if not (bitsBase >= 0x8000 and bitsBase <= 0x7fffff):
            raise BaseException("Second part of bits should be in [0x8000, 0x7fffff]")
        return bitsBase << (8 * (bitsN-3))

    def target_to_bits(self, target):
        c = ("%064x" % target)[2:]
        while c[:2] == '00' and len(c) > 6:
            c = c[2:]
        bitsN, bitsBase = len(c) // 2, int('0x' + c[:6], 16)
        if bitsBase >= 0x800000:
            bitsN += 1
            bitsBase >>= 8
        return bitsN << 24 | bitsBase

    def can_connect(self, header, check_height=True):
        height = header['block_height']
        if check_height and self.height() != height - 1:
            #self.print_error("cannot connect at height", height)
            return False
        if height == 0:
            return hash_header(header) == bitcoin.NetworkConstants.GENESIS
        try:
            prev_hash = self.get_hash(height - 1)
        except:
            return False
        if prev_hash != header.get('prev_block_hash'):
            return False
        target = self.get_target(height - 1)
        try:
            self.verify_header(header, prev_hash, target)
        except BaseException as e:
            return False
        return True

    def connect_chunk(self, idx, hexdata):
        try:
            data = bfh(hexdata)
            self.verify_chunk(idx, data)
            #self.print_error("validated chunk %d" % idx)
            self.save_chunk(idx, data)
            return True
        except BaseException as e:
            self.print_error('verify_chunk failed', str(e))
            return False

    def get_checkpoints(self):
        # for each chunk, store the hash of the last block and the target after the chunk
        cp = []
        n = self.height() // 2016
        for index in range(n):
            h = self.get_hash((index+1) * 2016 -1)
            target = self.get_target(index)
            cp.append((h, target))
        return cp
