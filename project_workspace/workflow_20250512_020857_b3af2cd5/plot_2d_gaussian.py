import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

def gaussian_2d(x, y, mu_x, mu_y, sigma_x, sigma_y):
    """2次元ガウス関数"""
    return np.exp(-((x - mu_x)**2 / (2 * sigma_x**2) + (y - mu_y)**2 / (2 * sigma_y**2)))

# パラメータ設定
mu_x = 0
mu_y = 0
sigma_x = 1
sigma_y = 2

# データ生成
x = np.arange(-5, 5, 0.25)
y = np.arange(-5, 5, 0.25)
X, Y = np.meshgrid(x, y)
Z = gaussian_2d(X, Y, mu_x, mu_y, sigma_x, sigma_y)

# 3Dプロット
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
ax.plot_surface(X, Y, Z)
ax.set_xlabel('x')
ax.set_ylabel('y')
ax.set_zlabel('z')
plt.title('2D Gaussian Function')
plt.savefig('gaussian_plot.png')

