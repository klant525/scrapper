from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import hashlib, json, time
from datetime import datetime

@dataclass
class Block:
    index: int
    timestamp: float
    data: Dict[str, Any]
    previous_hash: str
    nonce: int = 0
    hash: str = ""

    def compute_hash(self) -> str:
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce
        }, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(block_string).hexdigest()

    def to_dict(self):
        d = asdict(self)
        d['timestamp'] = datetime.fromtimestamp(self.timestamp).isoformat()
        return d

class Blockchain:
    def __init__(self, difficulty: int = 3):
        self.chain: List[Block] = []
        self.difficulty = difficulty
        self.create_genesis_block()

    def create_genesis_block(self):
        if self.chain:
            return
        genesis = Block(0, time.time(), {"note": "genesis block"}, "0")
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def proof_of_work(self, block: Block) -> str:
        target = '0' * self.difficulty
        while True:
            computed = block.compute_hash()
            if computed.startswith(target):
                return computed
            block.nonce += 1

    def add_block(self, data: Dict[str, Any]) -> Block:
        new_block = Block(
            index=self.last_block.index + 1,
            timestamp=time.time(),
            data=data,
            previous_hash=self.last_block.hash
        )
        new_block.hash = self.proof_of_work(new_block)
        self.chain.append(new_block)
        return new_block

    def is_chain_valid(self):
        target = '0' * self.difficulty
        for i in range(1, len(self.chain)):
            current = self.chain[i]
            prev = self.chain[i - 1]
            if current.hash != current.compute_hash():
                return False, f'Invalid hash at index {current.index}'
            if current.previous_hash != prev.hash:
                return False, f'Invalid previous_hash at index {current.index}'
            if not current.hash.startswith(target):
                return False, f'Proof-of-work not satisfied at index {current.index}'
        return True, 'Chain is valid'

    def to_list(self):
        return [b.to_dict() for b in self.chain]

    def save_to_file(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_list(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, path: str, difficulty: int = 3):
        with open(path, 'r', encoding='utf-8') as f:
            arr = json.load(f)
        bc = cls(difficulty=difficulty)
        # replace genesis with loaded genesis
        bc.chain = []
        for item in arr:
            b = Block(
                index=item['index'],
                timestamp=datetime.fromisoformat(item['timestamp']).timestamp(),
                data=item['data'],
                previous_hash=item['previous_hash'],
                nonce=item.get('nonce', 0),
                hash=item.get('hash', "")
            )
            bc.chain.append(b)
        return bc
