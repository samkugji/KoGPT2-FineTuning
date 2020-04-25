import torch
from torch.utils.data import DataLoader # 데이터로더
from gluonnlp.data import SentencepieceTokenizer 
from kogpt2.utils import get_tokenizer
from kogpt2.utils import download, tokenizer
from kogpt2.model.torch_gpt2 import GPT2Config, GPT2LMHeadModel
from util.data import NovelDataset
import gluonnlp
from kogpt2.model.sample import sample_sequence
from tqdm import tqdm
import subprocess
import generator
import os

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--epoch', type=int, default=200,
					help="epoch 를 통해서 학습 범위를 조절합니다.")
parser.add_argument('--save_path', type=str, default='./checkpoint/',
					help="학습 결과를 저장하는 경로입니다.")
parser.add_argument('--load_path', type=str, default='./checkpoint/KoGPT2_checkpoint_long.tar',
					help="학습된 결과를 불러오는 경로입니다.")
parser.add_argument('--samples', type=str, default="samples/",
					help="학습된 결과를 불러오는 경로입니다.")
parser.add_argument('--data_file_path', type=str, default='dataset/lyrics_dataset.txt',
					help="학습된 결과를 불러오는 경로입니다.")
parser.add_argument('--batch_size', type=int, default=8,
					help="batch_size 를 지정합니다.")
args = parser.parse_args()

ctx = 'cuda'
cachedir = '~/kogpt2/'

pytorch_kogpt2 = {
	'url':
	'checkpoint/pytorch_kogpt2_676e9bcfa7.params',
	'fname': 'pytorch_kogpt2_676e9bcfa7.params',
	'chksum': '676e9bcfa7'
}
kogpt2_config = {
	"initializer_range": 0.02,
	"layer_norm_epsilon": 1e-05,
	"n_ctx": 1024,
	"n_embd": 768,
	"n_head": 12,
	"n_layer": 12,
	"n_positions": 1024,
	"vocab_size": 50000
}


def get_gpu_memory_map():
	"""Get the current gpu usage.

	Returns
	-------
	usage: dict
		Keys are device ids as integers.
		Values are memory usage as integers in MB.
	"""
	result = subprocess.check_output(
		[
			'nvidia-smi', '--query-gpu=memory.used',
			'--format=csv,nounits,noheader'
		], encoding='utf-8')
	# Convert lines into a dictionary
	gpu_memory = [int(x) for x in result.strip().split('\n')]
	gpu_memory_map = dict(zip(range(len(gpu_memory)), gpu_memory))
	return gpu_memory_map


def main(epoch, save_path, load_path, samples, data_file_path, batch_size):
	# download model
	model_info = pytorch_kogpt2
	model_path = download(model_info['url'],
						   model_info['fname'],
						   model_info['chksum'],
						   cachedir=cachedir)
	# download vocab
	vocab_info = tokenizer
	vocab_path = download(vocab_info['url'],
						   vocab_info['fname'],
						   vocab_info['chksum'],
						   cachedir=cachedir)

	# KoGPT-2 언어 모델 학습을 위한 GPT2LMHeadModel 선언
	kogpt2model = GPT2LMHeadModel(config=GPT2Config.from_dict(kogpt2_config))

	# model_path 로부터 다운로드 받은 내용을 load_state_dict 으로 업로드
	kogpt2model.load_state_dict(torch.load(model_path))

	device = torch.device(ctx)
	kogpt2model.to(device)

	# 불러오기 부분
	if load_path:
		checkpoint = torch.load(load_path, map_location=device)

		# KoGPT-2 언어 모델 학습을 위한 GPT2LMHeadModel 선언
		kogpt2model = GPT2LMHeadModel(config=GPT2Config.from_dict(kogpt2_config))
		kogpt2model.load_state_dict(checkpoint['model_state_dict'])

		kogpt2model.eval()

	# 추가로 학습하기 위해 .train() 사용
	kogpt2model.train()
	vocab_b_obj = gluonnlp.vocab.BERTVocab.from_sentencepiece(vocab_path,
														 mask_token=None,
														 sep_token=None,
														 cls_token=None,
														 unknown_token='<unk>',
														 padding_token='<pad>',
														 bos_token='<s>',
														 eos_token='</s>')

	tok_path = get_tokenizer()
	model, vocab = kogpt2model, vocab_b_obj
	sentencepieceTokenizer = SentencepieceTokenizer(tok_path)

	novel_dataset = NovelDataset(data_file_path, vocab,sentencepieceTokenizer)
	novel_data_loader = DataLoader(novel_dataset, batch_size=batch_size, shuffle=True, pin_memory=True)

	learning_rate = 3e-5
	criterion = torch.nn.CrossEntropyLoss()
	optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

	## train
	tok_path = get_tokenizer()
	model, vocab = kogpt2model, vocab_b_obj
	model = model.to(ctx)
	tok = SentencepieceTokenizer(tok_path)

	print('KoGPT-2 Transfer Learning Start')
	avg_loss = (0.0, 0.0)
	for epoch in range(epoch):
		count = 0
		for data in novel_data_loader:
			optimizer.zero_grad()
			data = torch.stack(data) # list of Tensor로 구성되어 있기 때문에 list를 stack을 통해 변환해준다.
			data = data.transpose(1,0)
			data = data.to(ctx)

			outputs = model(data, labels=data)
			loss, logits = outputs[:2]
			loss = loss.to(ctx)
			loss.backward()
			avg_loss = (avg_loss[0] * 0.99 + loss, avg_loss[1] * 0.99 + 1.0)
			optimizer.step()
			if count % 10 == 0:
				print('epoch no.{0} train no.{1}  loss = {2:.5f} avg_loss = {3:.5f}' . format(epoch, count, loss, avg_loss[0] / avg_loss[1]))
				# torch.save(model,save_path+'checkpoint_{}_{}.tar'.format(epoch,count))
				# 추론 및 학습 재개를 위한 일반 체크포인트 저장하기
			# generator 진행
			if (count > 0 and count % 100 == 0) or (len(data) < batch_size):
				sent = sample_sequence(model, tok, vocab, sent="사랑", text_size=100, temperature=0.7, top_p=0.8, top_k=40)

				print(sent)

				now = [int(n) for n in os.listdir(samples)]
				now = max(now)
				f = open(samples + str(now + 1), 'w', encoding="utf-8")
				f.write(sent)
				f.close()
			#########################################
			if (count > 0 and count % 10000 == 0) or (len(data) < batch_size):
				# 모델 저장
				try:
					torch.save({
						'epoch': epoch,
						'train_no': count,
						'model_state_dict': model.state_dict(),
						'optimizer_state_dict': optimizer.state_dict(),
						'loss':loss
					}, save_path+ 'KoGPT2_checkpoint_' + count + '.tar')
				except:
					pass
		count += 1

if __name__ == "__main__":
	# execute only if run as a script
	epoch = args.epoch  # 학습 epoch
	save_path = args.save_path
	load_path = args.load_path
	samples = args.samples
	data_file_path = args.data_file_path
	batch_size = args.batch_size

	main(epoch, save_path, load_path, data_file_path, batch_size)