import os
import sys
import random
import torch
from torch.utils.data import DataLoader # 데이터로더
from gluonnlp.data import SentencepieceTokenizer 
from kogpt2.utils import get_tokenizer
from kogpt2.utils import download, tokenizer
from kogpt2.model.modeling_gpt2 import GPT2Config, GPT2LMHeadModel
from util.data import NovelDataset
import gluonnlp
from tqdm import tqdm
import subprocess

### 2.2. koGPT-2 Config

ctx= 'cuda'#'cuda' #'cpu' #학습 Device CPU or GPU. colab의 경우 GPU 사용
cachedir='~/kogpt2/' # KoGPT-2 모델 다운로드 경로
epoch =200  # 학습 epoch
save_path = 'checkpoint/'

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

### 2.7. KoGPT-2 Transfer Laerning

def main():
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


	### 2.4.KoGPT-2 Model Vocab

	# KoGPT-2 언어 모델 학습을 위한 GPT2LMHeadModel 선언
	kogpt2model = GPT2LMHeadModel(config=GPT2Config.from_dict(kogpt2_config))
	# model_path로부터 다운로드 받은 내용을 load_state_dict으로 업로드
	kogpt2model.load_state_dict(torch.load(model_path))

	device = torch.device(ctx)
	kogpt2model.to(device)

	# kogpt2model.eval()
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
	### 2.5. Get Batch Data using DataLoader

	tok_path = get_tokenizer()
	model, vocab = kogpt2model, vocab_b_obj
	sentencepieceTokenizer = SentencepieceTokenizer(tok_path)

	#os.chdir("../")
	data_file_path = 'dataset/lyrics_dataset.txt'
	batch_size = 8 # 이 부분을 수정하면 학습을 못하는건가?
	novel_dataset = NovelDataset(data_file_path, vocab,sentencepieceTokenizer)
	novel_data_loader = DataLoader(novel_dataset, batch_size=batch_size, shuffle=True, pin_memory=True)

	### 2.6. Learning rate, Loss function, Adam Optimizer

	learning_rate = 1e-5
	criterion = torch.nn.CrossEntropyLoss()
	optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)


	## train 

	tok_path = get_tokenizer()
	model, vocab = kogpt2model, vocab_b_obj
	model = model.to(ctx)
	tok = SentencepieceTokenizer(tok_path)

	print('KoGPT-2 Transfer Learning Start')
	epoch=200
	avg_loss = (0.0, 0.0)
	for epoch in range(epoch):
	    count = 0
	    for data in novel_data_loader:
	        optimizer.zero_grad()
	        data = torch.stack(data) # list of Tensor로 구성되어 있기 때문에 list를 stack을 통해 변환해준다.

	        data= data.transpose(1,0)
	        data= data.to(ctx)

	        outputs = model(data, labels=data)
	        loss, logits = outputs[:2]
	        loss = loss.to(ctx)
	        loss.backward()
	        avg_loss = (avg_loss[0] * 0.99 + loss, avg_loss[1] * 0.99 + 1.0)
	        optimizer.step()
	        if count %10 ==0:
	            print('epoch no.{0} train no.{1}  loss = {2:.5f} avg_loss = {3:.5f}' . format(epoch, count, loss, avg_loss[0] / avg_loss[1]))
	            # torch.save(model,save_path+'checkpoint_{}_{}.tar'.format(epoch,count))
	            # 추론 및 학습 재개를 위한 일반 체크포인트 저장하기
	        #########################################
	        if (count >0 and count%1000==0) or (len(data) < batch_size):
	            # 생성하는 부분
	            sent =''
	            tmp_sent = "사랑"
	            sent = sent+tmp_sent

	            toked = tok(sent)
	            counts = 0
	            generated_text =''
	            input_size = 50 #이걸 1024로 나중에는 바꾸면 되고

	            if len(toked) >1022:
	                break

	            while 1:
	                input_ids = torch.tensor([vocab[vocab.bos_token],]  + vocab[toked]).unsqueeze(0)
	                input_ids = input_ids.to(ctx)
	                predicts = model(input_ids)
	                pred = predicts[0]
	                gen = vocab.to_tokens(torch.argmax(pred, axis=-1).squeeze().tolist())[-1]
	                #if gen == '</s>':
	                #	print('to_tokens:',vocab.to_tokens(torch.argmax(pred, axis=-1).squeeze().tolist()))
	                if gen == '.' or counts>input_size: # 이 부분을 수정해서 재생성 결과 바꾸기
	                    sent += gen.replace('▁', ' ')
	                    generated_text += gen.replace('▁', ' ')
	                    sent += '\n'
	                    generated_text += '\n'
	                    toked = tok(sent)
	                    counts =0
	                    break
	                  # print('to_tokens:',vocab.to_tokens(torch.argmax(pred, axis=-1).squeeze().tolist()))
	                # if counts >= input_size:
	                #   break
	                sent += gen.replace('▁', ' ')
	                generated_text += gen.replace('▁', ' ')
	                # print(generated_text)

	                toked = tok(sent)
	                counts += 1
	            print(sent)
	            generated_text=''
	        #########################################
	        if (count >0 and count%10000==0) or (len(data) < batch_size):
	            # 모델 저장
	            try:
		            torch.save({
		                'epoch': epoch,
		                'train_no': count,
		                'model_state_dict': model.state_dict(),
		                'optimizer_state_dict': optimizer.state_dict(),
		                'loss':loss
		            }, save_path+ 'KoGPT2_checkpoint_long.tar')
		            # save_path+ 'KoGPT2_checkpoint_' + count + '.tar')
	            except:
		            pass
	        count += 1

if __name__ == "__main__":
    # execute only if run as a script
    main()