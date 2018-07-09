import subprocess
import json
from parameters import *

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

def AveragingInterval(height):
    # V1
    if height < nHeight_Difficulty_Version2:
        return nAveragingInterval_Version1
    # V2
    elif height < nHeight_Difficulty_Version3:
        return nAveragingInterval_Version2
    # V3
    else:
        return nAveragingInterval_Version3


def MinActualTimespan(height):
    print("height is " + str(height))
    averagingTargetTimespan = AveragingInterval(height) * nPowTargetSpacing
    # V1
    if height < nHeight_Difficulty_Version2:
        return averagingTargetTimespan * (100 - nMaxAdjustUp_Version1) / 100
    # V2
    elif height < nHeight_Difficulty_Version3:
        return averagingTargetTimespan * (100 - nMaxAdjustUp_Version2) / 100
    # V3
    else:
        return averagingTargetTimespan * (100 - nMaxAdjustUp_Version3) / 100


def MaxActualTimespan(height):
    averagingTargetTimespan = AveragingInterval(height) * nPowTargetSpacing
    # V1
    if height < nHeight_Difficulty_Version2:
        return averagingTargetTimespan * (100 + nMaxAdjustDown_Version1) / 100
    # V2
    elif height < nHeight_Difficulty_Version3:
        return averagingTargetTimespan * (100 + nMaxAdjustDown_Version2) / 100
    # V3
    else:
        return averagingTargetTimespan * (100 + nMaxAdjustDown_Version3) / 100


def DifficultyAdjustmentInterval(height):
    # V1
    if height < nHeight_Difficulty_Version2:
        return nInterval_Version1
    # V2
    if height < nHeight_Difficulty_Version3:
        return nInterval_Version2
    # V3
    return nInterval_Version3


def AveragingInterval(height):
    # V1
    if height < nHeight_Difficulty_Version2:
        return nAveragingInterval_Version1
    # V2
    if height < nHeight_Difficulty_Version3:
        return nAveragingInterval_Version2
    # V3
    return nAveragingInterval_Version3


def MinActualTimespan(height):
    averagingTargetTimespan = AveragingInterval(height) * nPowTargetSpacing
    # V1
    if height < nHeight_Difficulty_Version2:
        return averagingTargetTimespan * (100 - nMaxAdjustUp_Version1) / 100
     # V2
    if height < nHeight_Difficulty_Version3:
        return averagingTargetTimespan * (100 - nMaxAdjustUp_Version2) / 100
     # V3
    return averagingTargetTimespan * (100 - nMaxAdjustUp_Version3) / 100


def MaxActualTimespan(height):
    averagingTargetTimespan = AveragingInterval(height) * nPowTargetSpacing
    # V1
    if height < nHeight_Difficulty_Version2:
        return averagingTargetTimespan * (100 + nMaxAdjustDown_Version1) / 100
     # V2
    if height < nHeight_Difficulty_Version3:
        return averagingTargetTimespan * (100 + nMaxAdjustDown_Version2) / 100
     # V3
    return averagingTargetTimespan * (100 + nMaxAdjustDown_Version3) / 100


def TargetTimespan(height):
     # V1
    if height < nHeight_Difficulty_Version2:
        return nTargetTimespan_Version1
     # V2
    if height < nHeight_Difficulty_Version3:
        return nAveragingInterval_Version2 * nPowTargetSpacing
     # V3
    return nAveragingInterval_Version3 * nPowTargetSpacing


def bits_to_target(bits):
    bitsN = (bits >> 24) & 0xff
    if not (bitsN >= 0x03 and bitsN <= 0x1e):
        raise BaseException("First part of bits should be in [0x03, 0x1e]")
    bitsBase = bits & 0xffffff
    if not (bitsBase >= 0x8000 and bitsBase <= 0x7fffff):
        raise BaseException("Second part of bits should be in [0x8000, 0x7fffff]")
    return bitsBase << (8 * (bitsN - 3))


def target_to_bits(target):
    #print("TARGET IS " + str(target))
    c = ("%064x" % target)[2:]
    while c[:2] == '00' and len(c) > 6:
        c = c[2:]
    bitsN, bitsBase = len(c) // 2, int('0x' + c[:6], 16)
    if bitsBase >= 0x800000:
        bitsN += 1
        bitsBase >>= 8
    return bitsN << 24 | bitsBase


def CalculateNextWorkRequired(headerLast, firstBlockTime):
    temp =1
    nMinActualTimespan = int(MinActualTimespan(int(headerLast["height"]) + 1))
    nMaxActualTimespan = int(MaxActualTimespan(int(headerLast["height"]) + 1))

    #print("MinActualTimespan \t"+ str(nMinActualTimespan))
    #print("MaxActualTimespan \t" + str(nMaxActualTimespan))

    # Limit adjustment step
    nActualTimespan = headerLast["time"] - firstBlockTime
    if nActualTimespan < nMinActualTimespan:
        nActualTimespan = nMinActualTimespan
    if nActualTimespan > nMaxActualTimespan:
        nActualTimespan = nMaxActualTimespan

     # Retarget
    #print("bits " + str(headerLast["bits"]))
    bnNewBits = int(headerLast["bits"], 16)
    #print("bits " + str(bnNewBits))
    # print(type(bnNewBits))
    bnNew = bits_to_target(bnNewBits)
    bnOld = bnNew
    # FLO: intermediate uint256 can overflow by 1 bit
    # const arith_uint256 bnPowLimit = UintToArith256(params.powLimit);
    # print(type(bnNew))
    #print("bnNew is " + str(bnNew))

    fShift = bnNew > MAX_TARGET - 1
    #print("fShift is " + str(fShift))
    if (fShift):
        bnNew = bnNew >> 1
    bnNew = bnNew * nActualTimespan
    bnNew = bnNew / TargetTimespan(headerLast["height"] + 1)
    if fShift:
        bnNew = bnNew << 1

    if bnNew > MAX_TARGET:
        bnNew = MAX_TARGET

    bnNew = target_to_bits(int(bnNew))
    return bnNew


def findNextTarget(headerLast):
    # read header for the height
    # 11115
    height = headerLast["height"]
    #print(int(headerLast["bits"], 16))
    # print(headerLast["result"]["block_height"])

    #print(DifficultyAdjustmentInterval(height + 1))

    # check if the height passes is in range for retargeting
    if (height + 1) % DifficultyAdjustmentInterval(height + 1) != 0:
        # print(headerLast["result"]["bits"])
        return int(headerLast["bits"], 16)

    # printing the height of last block
    #print("last " + str(height))

    # Later part of the function
    averagingInterval = AveragingInterval(height + 1)
    blockstogoback = averagingInterval - 1
    #print("Blocks to go back = " + str(blockstogoback))
    if (height + 1) != averagingInterval:
        blockstogoback = averagingInterval

    # print(blockstogoback)
    firstHeight = height - blockstogoback
    #print("first " + str(firstHeight))

    # read header for the firstHeight
    block_hash = subprocess.check_output(["flo-cli", "getblockhash", str(int(firstHeight))])
    block_hash = block_hash.decode("utf-8")
    block_header = subprocess.check_output(["flo-cli", "getblockheader", str(block_hash)])
    block_header = block_header.decode("utf-8")
    headerFirst = json.loads(block_header)
    #print(int(headerFirst["bits"], 16))

    return CalculateNextWorkRequired(headerLast, headerFirst["time"])

prev_target = -12
latest = subprocess.check_output(["flo-cli", "getblockcount"])
latest = int(latest)


for i in range(426000, latest):
    #print(i)
    block_hash = subprocess.check_output(["flo-cli", "getblockhash", str(i)])
    block_hash = block_hash.decode("utf-8")
    block_header = subprocess.check_output(["flo-cli", "getblockheader", str(block_hash)])
    block_header = block_header.decode("utf-8")
    headerLast = json.loads(block_header)
    calculated_target = findNextTarget(headerLast)

    if i == 426000:
        prev_target = calculated_target
        continue

    if int(headerLast["bits"],16) == prev_target:
        print(str(i) + "  cool")
        prev_target = calculated_target
    else:
        print(str(i) + str(" something is wrong"))
        break



