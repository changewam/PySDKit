# -*- coding: utf-8 -*-
"""
Created on 2025/01/11 10:33:21
@author: Whenxuan Wang
@email: wwhenxuan@gmail.com
"""
import numpy as np
from numpy.linalg import norm
from scipy.integrate import cumulative_trapezoid
from scipy.sparse import spdiags, vstack, hstack, eye
from scipy.sparse.linalg import spsolve

from pysdkit.vmd.base import Base

from typing import Optional, Tuple, Union


class ACMD(Base):
    """
    Detection of Rub-Impact Fault for Rotor-Stator Systems: A Novel Method Based on Adaptive Chirp Mode Decomposition,
    Chen S, Yang Y, Peng Z, et al,
    Journal of Sound and Vibration, 2018.
    https://www.mathworks.com/matlabcentral/fileexchange/69128-adaptive-chirp-mode-decomposition
    """

    def __init__(self, K: int, fs: Optional[int] = None, alpha0: float = 1e-3, beta: float = 1e-4,
                 tol: float = 1e-8, max_iter: int = 300) -> None:
        """
        :param K: 表示迭代几次获取
        :param fs: sampling frequency of inputs signal.
        :param alpha0: penalty parameter controling the filtering bandwidth of ACMD;the smaller the alpha0 is, the narrower the bandwidth would be,
               if this parameter is larger, it will help the algorithm to find correct modes even the initial IFs are too rough. But it will introduce more noise and also may increase the interference between the signal modes.
        :param beta: penalty parameter controling the smooth degree of the IF increment during iterations;the smaller the beta is, the more smooth the IF increment would be.
        :param tol: tolerance of convergence criterion; typically 1e-7, 1e-8, 1e-9...
        :param max_iter: the maximum allowable iterations.
        """
        super().__init__()
        # 迭代分解的次数或是本征模态函数的数目
        self.K = K
        self.fs = fs
        self.alpha0 = alpha0
        self.beta = beta
        self.tol = tol
        self.max_iter = max_iter

    @staticmethod
    def init_IF1(signal: np.ndarray, SampFreq: int, N: int):
        """Initial instantaneous frequency (IF) time series of a certain signal mode,a row vector"""
        Spec = 2 * np.abs(np.fft.fft(signal)) / N  # 计算信号的 FFT
        Spec = Spec[:len(Spec) // 2 + 1]  # 取频谱的前半部分
        Freqbin = np.linspace(0, SampFreq / 2, len(Spec))  # 生成频率轴
        # Component 1 extraction
        findex1 = np.argmax(Spec)
        # IF initialization by finding peak frequency of the Fourier spectrum
        peakfre1 = Freqbin[findex1]
        iniIF = peakfre1 * np.ones(N)
        return iniIF

    @staticmethod
    def differ(y: np.ndarray, delta: float, dtype: np.dtype = np.float64) -> np.ndarray:
        """
        Compute the derivative of a discrete time series y.
        :param y: The input time series.
        :param delta: The sampling time interval of y.
        :param dtype: The data type of numpy array
        :return: numpy.ndarray: The derivative of the time series.
        """
        L = len(y)
        ybar = np.zeros(L - 2, dtype=dtype)

        for i in range(1, L - 1):
            ybar[i - 1] = (y[i + 1] - y[i - 1]) / (2 * delta)

        # Prepend and append the boundary differences
        ybar = np.concatenate((np.array([(y[1] - y[0]) / delta], dtype=dtype),
                               ybar, np.array([(y[-1] - y[-2]) / delta], dtype=dtype)))

        return ybar

    def iter(self, signal: np.ndarray, eIF: np.ndarray, N: int, fs: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """迭代一次算法"""
        # Initialize
        e = np.ones(N)
        e2 = -2 * e

        t = np.linspace(0, 1, self.fs)

        # 生成二阶差分矩阵 oper
        data = np.vstack((e[:-2], e2[1:-1], e[2:]))
        diags = np.array([0, 1, 2])
        oper = spdiags(data, diags, N - 2, N)

        # 生成 (K-2) x K 的零矩阵 spzeros
        spzeros = spdiags([np.zeros(N)], [0], N - 2, N)

        # 计算 oper 的转置与 oper 的乘积
        opedoub = oper.T @ oper

        # 生成块矩阵 phim
        phim = vstack((hstack((oper, spzeros)), hstack((spzeros, oper))))

        # 计算 phim 的转置与 phim 的乘积
        phidoubm = phim.T @ phim

        # The collection of the obtained IF time series of the signal modes at each iteration
        IFsetiter = np.zeros([self.max_iter, N])
        # The collection of the obtained signal modes at each iteration
        ssetiter = np.zeros([self.max_iter, N])
        ysetiter = np.zeros([self.max_iter, 2 * N])

        # Begin the iterations
        n = 0  # iteration counter
        sDif = self.tol + 1
        alpha = self.alpha0

        pi = np.pi

        while sDif > self.tol and n < self.max_iter:
            # 计算累积梯形积分
            cumulative_integral = cumulative_trapezoid(eIF, t, initial=0)

            # 计算余弦和正弦函数
            cosm = np.cos(2 * pi * cumulative_integral)
            sinm = np.sin(2 * pi * cumulative_integral)
            # 将 cosm 和 sinm 转换为列向量
            cosm_col = cosm.reshape(-1, 1)
            sinm_col = sinm.reshape(-1, 1)

            # 创建稀疏对角矩阵 Cm 和 Sm
            Cm = spdiags(cosm_col[:, 0], 0, N, N).tocsc()
            Sm = spdiags(sinm_col[:, 0], 0, N, N).tocsc()

            # 组合成核矩阵 Kerm
            Kerm = hstack((Cm, Sm))

            # 计算 Kerm 的转置与 Kerm 的乘积
            Kerdoubm = Kerm.T @ Kerm

            # Update demodulated signals
            A = (1 / alpha * phidoubm + Kerdoubm)
            B = (Kerm.T * signal)
            # A * x = B
            ym = spsolve(A, B)  # the demodulated target signal
            si = Kerm * ym  # the signal component
            ssetiter[n, :] = si
            ysetiter[n, :] = ym

            # Update the IFs
            ycm, ysm = (ym[:N].copy()).T, (ym[N:].copy()).T  # the demodulated target signal
            # compute the derivative of the functions
            ycmbar, ysmbar = self.differ(ycm, 1 / fs), self.differ(ysm, 1 / fs)
            # Obtain the frequency increment by arctangent demodulation
            deltaIF = (ycm * ysmbar - ysm * ycmbar) / (ycm ** 2 + ysm ** 2) / (2 * pi)
            # Smooth the frequency increment by low pass filtering
            deltaIF = spsolve((1 / self.beta * opedoub + eye(N, format='csr')), deltaIF.T)
            eIF = eIF - deltaIF  # update the IF
            IFsetiter[n, :] = eIF

            # Compute the convergence index
            if n > 0:
                sDif = (norm(ssetiter[n, :] - ssetiter[n - 1]) / norm(ssetiter[n - 1, :])) ** 2

            n = n + 1

        # Maximum iteration
        n = n - 1
        # Estimated IF
        IFest = IFsetiter[n, :]
        # Estimated signal mode
        sest = ssetiter[n, :]
        ycm = ysetiter[n, :N]
        ysm = ysetiter[n, N:]
        # Estimated IA
        IAest = (np.sqrt(ycm ** 2 + ysm ** 2))

        return sest, IFest, IAest

    def fit_transform(self, signal: np.ndarray, return_all: Optional[bool] = False
                      ) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """开始进行ACMD算法"""
        # Initialize
        N = len(signal)  # K is the number of the samples
        if self.fs is None:
            fs = N
        else:
            fs = self.fs
        t = np.arange(0, N) / fs  # Time

        # 初始化记录每次结果的数组
        IMFs, IFests, IAests = np.zeros([self.K, N]), np.zeros([self.K, N]), np.zeros([self.K, N])

        # 开始迭代式分解
        for ii in range(self.K):
            # The initialization of peak frequency
            eIF = self.init_IF1(signal=signal, SampFreq=fs, N=N)
            # 进行一次分解
            sest, IFest, IAest = self.iter(signal=signal, eIF=eIF, N=N, fs=fs)
            # 记录本次分解的结果
            IMFs[ii, :] = sest
            IFests[ii, :] = IFest
            IAests[ii, :] = IAest
            # 将本次分解的残差作为下一次迭代的输入
            signal = signal - sest  # obtain the residual signal by the extracted component from the raw signal

        if return_all is True:
            return IMFs, IFests, IAests
        return IMFs
