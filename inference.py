"""
    Small script for testing on few generic images given the model weights.
    In order to minimize the requirements, it runs only on CPU and images are
    processed one by one.
"""
import requests
import torch
import argparse
import pickle
import cv2
import numpy as np
from argparse import Namespace
from models.End_ExpansionNet_v2 import End_ExpansionNet_v2
from utils.image_utils import preprocess_image
from utils.language_utils import tokens2description
import threading
import time
import torchvision
from PIL import Image as PIL_Image
from sound import speak

global frame
frame = None

def get_live_feed():
    global frame
    # link to camera feed from camera
    url = "http://192.168.1.157:8080/shot.jpg"
    cap = cv2.VideoCapture(0)  # 0 is usually the default camera

    # Check if the camera opened successfully
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    i = 0
    while True:
        img_size = 384
        img_resp = requests.get(url)
        img_arr = np.array(bytearray(img_resp.content), dtype=np.uint8)
        img_arr = cv2.imdecode(img_arr, -1) 
        # img_rgb = cv2.cvtColor(img_arr, cv2.COLOR_BGR2RGB)

        transf_1 = torchvision.transforms.Compose([torchvision.transforms.Resize((img_size, img_size))])
        transf_2 = torchvision.transforms.Compose([torchvision.transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                                                                    std=[0.229, 0.224, 0.225])])

        pil_image = PIL_Image.fromarray(img_arr)
        if pil_image.mode != 'RGB':
            pil_image = PIL_Image.new("RGB", pil_image.size)
        preprocess_pil_image = transf_1(pil_image)
        image = torchvision.transforms.ToTensor()(preprocess_pil_image)
        image = transf_2(image)
        
        img = image.numpy()
        # img_trans = np.transpose(img, (1, 2, 0))
        # print(frame.shape)
        frame = np.transpose(img, (1, 2, 0))

        # Display the resulting frame
        cv2.imshow('Live Video Feed', frame)
    
        # Press 'q' on keyboard to exit the program
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        i+=1

    # release the video capture object, When everything done
    # cap.release()
    cv2.destroyAllWindows()
    frame = None

def main():
    parser = argparse.ArgumentParser(description='Inference')
    parser.add_argument('--model_dim', type=int, default=512)
    parser.add_argument('--N_enc', type=int, default=3)
    parser.add_argument('--N_dec', type=int, default=3)
    parser.add_argument('--max_seq_len', type=int, default=74)
    parser.add_argument('--load_path', type=str, default='./checkpoints/rf_model.pth')
    parser.add_argument('--image_paths', type=str,
                        default=['./utilities/tatin.jpg',
                                 './utilities/micheal.jpg',
                                 './utilities/napoleon.jpg',
                                 './utilities/cat_girl.jpg'],
                        nargs='+')
    parser.add_argument('--beam_size', type=int, default=5)

    args = parser.parse_args()

    drop_args = Namespace(enc=0.0,
                          dec=0.0,
                          enc_input=0.0,
                          dec_input=0.0,
                          other=0.0)
    model_args = Namespace(model_dim=args.model_dim,
                           N_enc=args.N_enc,
                           N_dec=args.N_dec,
                           dropout=0.0,
                           drop_args=drop_args)

    with open('./utilities/tokens.pickle', 'rb') as f:
        coco_tokens = pickle.load(f)
        sos_idx = coco_tokens['word2idx_dict'][coco_tokens['sos_str']]
        eos_idx = coco_tokens['word2idx_dict'][coco_tokens['eos_str']]

    print("Dictionary loaded ...")

    img_size = 384
    model = End_ExpansionNet_v2(swin_img_size=img_size, swin_patch_size=4, swin_in_chans=3,
                                swin_embed_dim=192, swin_depths=[2, 2, 18, 2], swin_num_heads=[6, 12, 24, 48],
                                swin_window_size=12, swin_mlp_ratio=4., swin_qkv_bias=True, swin_qk_scale=None,
                                swin_drop_rate=0.0, swin_attn_drop_rate=0.0, swin_drop_path_rate=0.0,
                                swin_norm_layer=torch.nn.LayerNorm, swin_ape=False, swin_patch_norm=True,
                                swin_use_checkpoint=False,
                                final_swin_dim=1536,

                                d_model=model_args.model_dim, N_enc=model_args.N_enc,
                                N_dec=model_args.N_dec, num_heads=8, ff=2048,
                                num_exp_enc_list=[32, 64, 128, 256, 512],
                                num_exp_dec=16,
                                output_word2idx=coco_tokens['word2idx_dict'],
                                output_idx2word=coco_tokens['idx2word_list'],
                                max_seq_len=args.max_seq_len, drop_args=model_args.drop_args,
                                rank='cpu')
    checkpoint = torch.load(args.load_path, map_location=torch.device('cpu'))
    model.load_state_dict(checkpoint['model_state_dict'])
    print("Model loaded ...")

    input_images = []
    for path in args.image_paths:
        input_images.append(preprocess_image(path, img_size))

    print("Generating captions ...\n")
    for i in range(len(input_images)):
        path = args.image_paths[i]
        image = input_images[i]
        beam_search_kwargs = {'beam_size': args.beam_size,
                              'beam_max_seq_len': args.max_seq_len,
                              'sample_or_max': 'max',
                              'how_many_outputs': 1,
                              'sos_idx': sos_idx,
                              'eos_idx': eos_idx}
        with torch.no_grad():
            pred, _ = model(enc_x=image,
                            enc_x_num_pads=[0],
                            mode='beam_search', **beam_search_kwargs)
        pred = tokens2description(pred[0][0], coco_tokens['idx2word_list'], sos_idx, eos_idx)
        print(path + ' \n\tDescription: ' + pred + '\n')

if __name__ == "__main__":
    main()