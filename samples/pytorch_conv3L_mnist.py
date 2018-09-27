#!/usr/bin/env python
#-----------------------------------------------------------------------------
# File Name : spikeConv2d.py
# Author: Emre Neftci
#
# Creation Date : Mon 16 Jul 2018 09:56:30 PM MDT
# Last Modified :
#
# Copyright : (c) UC Regents, Emre Neftci
# Licence : GPLv2
#-----------------------------------------------------------------------------
from dcll.pytorch_libdcll import *
from dcll.pytorch_utils import grad_parameters, named_grad_parameters, NetworkDumper
import timeit

def acc(pvoutput, labels):
    return float(torch.mean((pvoutput.argmax(1) == labels.argmax(1)).float()))

class ConvNetwork(torch.nn.Module):
    def __init__(self, im_dims, batch_size,
                 target_size, out_channels_1, out_channels_2, out_channels_3):
        super(ConvNetwork, self).__init__()
        self.layer1 = Conv2dDCLLlayer(in_channels, out_channels = out_channels_1,
                                      im_dims=im_dims, target_size=target_size,
                                      pooling=2, padding=3, kernel_size=7,
                                      act = torch.nn.ReLU()).to(device).init_hiddens(batch_size)
        o_shape = torch.Size([out_channels_1]) + self.layer1.output_shape
        self.layer2 = Conv2dDCLLlayer(out_channels_1, out_channels = out_channels_2,
                                      im_dims=(o_shape[1], o_shape[2]), target_size=target_size,
                                      pooling=2, padding=3, kernel_size=7,
                                      act = torch.nn.ReLU()).to(device).init_hiddens(batch_size)
        o_shape = torch.Size([out_channels_2]) + self.layer2.output_shape
        self.layer3 = Conv2dDCLLlayer(out_channels_2, out_channels = out_channels_3,
                                      im_dims=(o_shape[1], o_shape[2]), target_size=target_size,
                                      pooling=1, padding=3, kernel_size=7,
                                      act = torch.nn.ReLU()).to(device).init_hiddens(batch_size)
        self.init_weights()

    def init_weights(self):
        for m in self.modules():
            if isinstance(m, Conv2dDCLLlayer):
                param = None
                if isinstance(m.i2h.act, torch.nn.ReLU):
                    act = 'relu'
                elif isinstance(m.i2h.act, torch.nn.LeakyReLU) or isinstance(m.i2h.act, torch.nn.ELU):
                    act = 'leaky_relu'
                    param = self.negative_slope
                elif isinstance(m.i2h.act, torch.nn.ReLU):
                    act = 'relu'
                else:
                    act = 'tanh'
                gain = torch.nn.init.calculate_gain(act, param) * 0.1
                m.i2h.bias.data.mul_(gain)
                torch.nn.init.xavier_normal_(m.i2h.weight, gain=gain)
                torch.nn.init.xavier_normal_(m.i2o.weight, gain=gain)

    def init_weights_from_batches(self, batches, var_tolerance = 0.01, tmax = 30):
        with torch.no_grad():
            spiketrains = batches
            for layer in [ self.layer1, self.layer2, self.layer3 ]:
                t = 0
                out = torch.stack( [ layer.forward(spike_img)[1] for spike_img in spiketrains ] )
                while torch.abs(torch.var(out) - 1.).item() > var_tolerance and t < tmax:
                    t += 1
                    layer.i2h.weight.data.mul_(1. / torch.std(out))
                    layer.i2h.bias.data.mul_(1. / torch.std(out))
                    out = torch.stack( [ layer.forward(spike_img)[1] for spike_img in spiketrains ] )
                print('out after {} with variance {}'.format(t, torch.var(out)))
                spiketrains = torch.stack( [ layer.forward(spike_img)[0] for spike_img in spiketrains ] )


    def zero_grad(self):
        self.layer1.zero_grad()
        self.layer2.zero_grad()
        self.layer3.zero_grad()

    def forward(self, x):
        output1, pvoutput1, _ = self.layer1.forward(x)
        output2, pvoutput2, _ = self.layer2.forward(output1)
        output3, pvoutput3, _ = self.layer3.forward(output2)
        return (output1, output2, output3), (pvoutput1, pvoutput2, pvoutput3)


if __name__ == '__main__':
    from tensorboardX import SummaryWriter
    writer = SummaryWriter(comment='MNIST Conv')

    torch.manual_seed(0)
    np.random.seed(0)

    n_epochs=200
    n_iters = 500
    in_channels = 1
    out_channels_1 = 32//2
    out_channels_2 = 48//2
    out_channels_3 = 64//2
    im_dims = (28, 28)
    batch_size = 64
    target_size = 10

    net = ConvNetwork(im_dims, batch_size, target_size, out_channels_1, out_channels_2, out_channels_3)
    dumper = NetworkDumper(writer, net)

    criterion = nn.MSELoss().to(device)
    optimizer = optim.SGD(grad_parameters(net), lr=5e-5)

    avg_loss1 = 0
    avg_loss2 = 0
    avg_loss3 = 0

    from dcll.load_mnist import *
    gen_train, gen_valid, gen_test = create_data(valid=False, batch_size = batch_size)

    for epoch in range(n_epochs):
        input, labels1h = image2spiketrain(*gen_train.next())

        input = torch.Tensor(input).to(device).reshape(n_iters,
                                                       batch_size,
                                                       in_channels,
                                                       *im_dims)
        if epoch == 0:
            # initialize network weight with respect to the first batch
            # Method described in "ALL YOU NEED IS A GOOD INIT", ICLR 2016
            net.init_weights_from_batches(input[0:200], var_tolerance = 1e-3)

        labels1h = torch.Tensor(labels1h).to(device)

        for iter in range(n_iters):
            if iter>150:
                optimizer.zero_grad()
                net.zero_grad()

            spikes, pvs = net.forward(input[iter])

            if iter>150:
                losses1 = criterion(pvs[0], labels1h[-1])
                losses2 = criterion(pvs[1], labels1h[-1])
                losses3 = criterion(pvs[2], labels1h[-1])

                avg_loss1 += losses1.item()
                avg_loss2 += losses2.item()
                avg_loss3 += losses3.item()

                losses1.backward()
                losses2.backward()
                losses3.backward()

                optimizer.step()

        writer.add_scalar('train/loss/layer1', avg_loss1 / n_iters, epoch)
        writer.add_scalar('train/loss/layer2', avg_loss2 / n_iters, epoch)
        writer.add_scalar('train/loss/layer3', avg_loss3 / n_iters, epoch)
        avg_loss1 = 0
        avg_loss2 = 0
        avg_loss3 = 0

        #print("Step time: {0}".format(time.time()-t0))
        print('TRAIN Epoch {0}: Acc1 {1:1.3} Acc2 {2:1.3} Acc3 {3:1.3}'.format(epoch, acc(pvs[0],labels1h[-1]), acc(pvs[1], labels1h[-1]), acc(pvs[2], labels1h[-1])))

        input, labels1h = image2spiketrain(*gen_test.next())
        input = torch.Tensor(input).to(device).reshape(n_iters,
                                                       batch_size,
                                                       in_channels,
                                                       *im_dims)
        labels1h = torch.Tensor(labels1h).to(device)

        for iter in range(n_iters-100):
            spikes, pvs = net.forward(input[iter])

            losses1 = criterion(pvs[0], labels1h[-1])
            losses2 = criterion(pvs[1], labels1h[-1])
            losses3 = criterion(pvs[2], labels1h[-1])

            avg_loss1 += losses1.item()
            avg_loss2 += losses2.item()
            avg_loss3 += losses3.item()

        avg_loss1 /= n_iters
        avg_loss2 /= n_iters
        avg_loss3 /= n_iters

        acc1 = acc(pvs[0], labels1h[-1])
        acc2 = acc(pvs[1], labels1h[-1])
        acc3 = acc(pvs[2], labels1h[-1])

        writer.add_scalar('test/loss/layer1', avg_loss1, epoch)
        writer.add_scalar('test/loss/layer2', avg_loss2, epoch)
        writer.add_scalar('test/loss/layer3', avg_loss3, epoch)

        writer.add_scalar('test/acc/layer1', acc1, epoch)
        writer.add_scalar('test/acc/layer2', acc2, epoch)
        writer.add_scalar('test/acc/layer3', acc3, epoch)

        dumper.histogram(t=epoch)

        print('Test Epoch {0}: L1 {1:1.3} L2 {2:1.3} L3{3:1.3} Acc1 {4:1.3} Acc2 {5:1.3} Acc3 {6:1.3}'.format(epoch, avg_loss1, avg_loss2, avg_loss3, acc1, acc2, acc3))

        #a = np.array(states1)
        #b = np.array(states2)
    writer.close()
