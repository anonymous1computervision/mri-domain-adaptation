import time

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from IPython.display import clear_output
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm


def run_one_epoch(model, loader, criterion, train, device, optimizer=None):
    model.to(device)
    model.train(train)

    losses = []
    probs = []
    targets = []

    for data, target in tqdm(loader):
        data = data.to(device, dtype=torch.float)
        target = target.long().to(device)
        outputs = model(data)
        loss = criterion(outputs, target)
        if train and optimizer is not None:
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        losses.append(loss.data.cpu().numpy())
        probs.extend(F.softmax(outputs, dim=-1).cpu().data.numpy()[:, 1])
        targets.extend(list(target.cpu().data.numpy()))
        del data, target, outputs, loss

    return losses, probs, targets


def train(
    model, optimizer, train_dataloader, val_dataloader, device,
    metric, verbose=0, model_save_path=None,
    max_epoch=1, eps=1e-3, max_patience=10):
    
    criterion = nn.CrossEntropyLoss()

    patience = 0
    best_metric = 0

    epoch_train_loss, last_train_loss, epoch_train_metric, last_train_metric, = [], None, [], None
    epoch_val_loss, last_val_loss, epoch_val_metric, last_val_metric, = [], None, [], None

    for epoch in range(max_epoch):
        start_time = time.time()

        # 1. Train
        train_losses, train_probs, train_targets = run_one_epoch(model, train_dataloader, criterion, True, device, optimizer)

        # 2. Inference
        if val_dataloader is not None:
            with torch.no_grad():
                val_losses, val_probs, val_targets = run_one_epoch(model, val_dataloader, criterion, False, device)

        # 3. Metrics
        epoch_train_loss.append(np.mean(train_losses))
        epoch_train_metric.append(metric(train_targets, train_probs))
        if val_dataloader is not None:
            epoch_val_loss.append(np.mean(val_losses))
            epoch_val_metric.append(metric(val_targets, val_probs))

        # 4. Print metrics
        if verbose:
            clear_output(True)
            print("Epoch {} of {} took {:.3f}s".format(epoch + 1, max_epoch, time.time() - start_time))
            print("  training loss (in-iteration): \t{:.6f}".format(epoch_train_loss[-1]))
            if val_dataloader is not None:
                print("  validation loss: \t\t\t{:.6f}".format(epoch_val_loss[-1]))
            print("  training {}: \t\t\t{:.2f}".format(metric.__name__, epoch_train_metric[-1]))
            if val_dataloader is not None:
                print("  validation {}: \t\t\t{:.2f}".format(metric.__name__, epoch_val_metric[-1]))    
            
        # 5. Plot metrics
        if verbose:
            fig, axes = plt.subplots(1, 2, figsize=(10, 5))
            plt.figure(figsize=(10, 5))
            axes[0].plot(epoch_train_loss, label='train')
            if val_dataloader is not None:
                axes[0].plot(epoch_val_loss, label='val')
            axes[0].set_xlabel('epoch')
            axes[0].set_ylabel('loss')
            axes[0].legend()
            axes[1].plot(epoch_train_metric, label='train')
            if val_dataloader is not None:
                axes[1].plot(epoch_val_metric, label='val')
            axes[1].set_ylim([0, 1.05])
            axes[1].set_xlabel('epoch')
            axes[1].set_ylabel(metric.__name__)
            axes[1].legend()
            plt.show()
        
        # 5. Early stopping, best metrics, save model
        if val_dataloader is not None:
            if epoch_val_metric[-1] > best_metric:
                patience = 0
                best_metric = epoch_val_metric[-1]
                last_train_metric, last_val_metric = epoch_train_metric[-1], epoch_val_metric[-1]
                last_train_loss, last_val_loss = epoch_train_loss[-1], epoch_val_loss[-1]
                if model_save_path is not None:
                    torch.save(model.state_dict(), model_save_path)
            else:
                patience += 1
                if patience >= max_patience:
                    print("Early stopping! Patience is out.")
                    break
            if epoch_val_loss[-1] < eps:
                print("Early stopping! Val loss < eps.")
                break
        else:
            if epoch_train_metric[-1] > best_metric:
                patience = 0
                best_metric = epoch_train_metric[-1]
                last_train_metric = epoch_train_metric[-1]
                last_train_loss = epoch_train_loss[-1]
                if model_save_path is not None:
                    torch.save(model.state_dict(), model_save_path)
            else:
                patience += 1
                if patience >= max_patience:
                    print("Early stopping! Patience is out.")
                    break
            if epoch_train_loss[-1] < eps:
                print("Early stopping! Train loss < eps.")
                break

    return last_train_loss, last_train_metric, last_val_loss, last_val_metric


def stratified_batch_indices(indices, labels):
    idx = sorted(indices, key=lambda x: labels[x])
    for i in range(0, len(indices) // 2, 2):
        idx[i], idx[len(indices) - 1 - i] = idx[len(indices) - 1 - i], idx[i]
    return idx


def cross_val_score(
    create_model_opt, dataset, cv, device, metric, model_load_path=None,
    batch_size=10):
    
    # if model_load_path is not None there is no training
    
    cv_splits = list(cv.split(X=np.arange(len(dataset)), y=dataset.labels))

    val_metrics = []

    for i in range(len(cv_splits)):
        train_idx, val_idx = cv_splits[i]
        model, optimizer = create_model_opt()

        if model_load_path is None:
            train_idx = stratified_batch_indices(train_idx, dataset.labels)
            train_loader = DataLoader(Subset(dataset, train_idx),
                                      shuffle=False,
                                      batch_size=batch_size,
#                                       num_workers=num_workers,
                                      drop_last=False)
            val_loader = DataLoader(Subset(dataset, val_idx),
                                    shuffle=False,
                                    batch_size=batch_size,
#                                     num_workers=num_workers,
                                    drop_last=False)
            _, _, _, last_val_metric = train(model, optimizer, train_loader, val_loader, device,
                                             metric=metric, verbose=1)
            val_metrics.append(last_val_metric)
            del train_loader
        else:
            model.load_state_dict(torch.load(model_load_path))
            val_loader = DataLoader(Subset(val_dataset, val_idx),
                                    shuffle=False,
                                    batch_size=batch_size,
                                    drop_last=False)
            with torch.no_grad():
                val_losses, val_probs, val_targets = run_one_epoch(model, val_dataloader, criterion, False, device)
            val_metric = metric(val_targets, val_probs)
            val_metrics.append(val_metric)
            
        del val_loader, model, optimizer

    return val_metrics