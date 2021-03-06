"""

"""
import SimPEG.PF as PF
from SimPEG import *
from SimPEG.Utils import io_utils
import matplotlib
import time as tm
import mpl_toolkits.mplot3d as a3
import matplotlib.colors as colors
import matplotlib.pyplot as plt
import scipy as sp
from scipy.interpolate import NearestNDInterpolator
from sklearn.mixture import GaussianMixture
import numpy as np
import copy
from pymatsolver import PardisoSolver

matplotlib.rcParams['font.size'] = 14

# Reproducible Science
np.random.seed(518936)

# We first need to create a susceptibility model.
# Based on a set of parametric surfaces representing TKC,
# we use VTK to discretize the 3-D space.
model_dir = '../Geology_Surfaces/'

# Create our own mesh!
mult_factor = 1.
csx, csy, csz = 10. / mult_factor, 10. / mult_factor, 10. / mult_factor
ncx, ncy, ncz = mult_factor * 60+1, mult_factor * 60+1, mult_factor * 50
npad = 10
hx = [(csx, npad, -1.25), (csx, ncx), (csx, npad, 1.25)]
hy = [(csy, npad, -1.25), (csy, ncy), (csy, npad, 1.25)]
hz = [(csz, npad, -1.25), (csz, ncz)]
mesh = Mesh.TensorMesh([hx, hy, hz], x0="CCN")
xc = 300 + 5.57e5
yc = 600 + 7.133e6
zc = 450.
x0_new = np.r_[mesh.x0[0] + xc, mesh.x0[1] + yc, mesh.x0[2] + zc]
mesh.x0 = x0_new

# Define no-data-value
ndv = -100

# Define survey flight height
Z_bird = csz/2.
print("Bird height: ", Z_bird)

# Read in topo surface
topofile = model_dir + 'TKCtopo.dat'
geosurf = [
    [model_dir + 'Till.ts', True, True, 0],
    [model_dir + 'PK1.ts', True, True, 2],
    [model_dir + 'PK2.ts', True, True, 3],
    [model_dir + 'PK3.ts', True, True, 4],
    [model_dir + 'HK1.ts', True, True, 5],
    [model_dir + 'VK.ts', True, True, 6]
]

print('mesh nC: ', mesh.nC)
# mesh.save('mesh_inverse')

# Create geological model
modelInd = np.ones(mesh.nC) * ndv
for ii in range(len(geosurf)):
    tin = tm.time()
    print("Computing indices with VTK: " + geosurf[ii][0])
    T, S = io_utils.read_GOCAD_ts(geosurf[ii][0])
    indx = io_utils.surface2inds(
        T, S, mesh,
        boundaries=geosurf[ii][1],
        internal=geosurf[ii][2]
    )
    print("VTK operation completed in " + str(tm.time() - tin) + " sec")
    modelInd[indx] = geosurf[ii][3]

# Fix artefact for PK1
idx = np.logical_and(modelInd == 2, mesh.gridCC[:, 1] < 350 + 7.133 * 1e6)
modelInd[idx] = ndv*np.ones_like(modelInd[idx])

# Load topography file in UBC format and find the active cells
# Import Topo
topofile = model_dir + 'TKCtopo.dat'
topo = np.genfromtxt(topofile, skip_header=1)
# Find the active cells
actv = Utils.surface2ind_topo(mesh, topo, gridLoc='N')
# Create active map to go from reduce set to full
actvMap = Maps.InjectActiveCells(mesh, actv, ndv)
print("Active cells created from topography!")


def getModel_grav(
    Till=0., XVK=0., PK1=-0.8, PK2=0., PK3=0., HK1=-0.2, VK=-0.8, bkgr=0.
):
    vals = [Till, XVK, PK1, PK2, PK3, HK1, VK]
    model = np.ones(mesh.nC) * bkgr

    for ii, den in zip(range(7), vals):
        model[modelInd == ii] = den
    return model

model = getModel_grav()
model = model[actv]


# Here you can visualize the current model
m_true = actvMap * model
airc = m_true == ndv
m_true[airc] = np.nan

# **Forward system:**
# We create a synthetic survey with observations in cell center.
X, Y = np.meshgrid(
    mesh.vectorCCx[npad:-npad:2],
    mesh.vectorCCy[npad:-npad:2]
)

# Using our topography, trape the survey and shift it up by the flight height
Ftopo = NearestNDInterpolator(topo[:, :2], topo[:, 2])
Z = Ftopo(Utils.mkvc(X.T), Utils.mkvc(Y.T)) + Z_bird

rxLoc = np.c_[Utils.mkvc(X.T), Utils.mkvc(Y.T), Utils.mkvc(Z.T)]
rxLoc = PF.BaseGrav.RxObs(rxLoc)
print('number of data: ', rxLoc.locs.shape[0])

srcField = PF.BaseGrav.SrcField([rxLoc])
survey = PF.BaseGrav.LinearSurvey(srcField)

# Now that we have a model and a survey we can build the linear system ...
nactv = np.int(np.sum(actv))
# Creat reduced identity map
idenMap = Maps.IdentityMap(nP=nactv)
# Create the forward model operator
prob = PF.Gravity.GravityIntegral(
    mesh, rhoMap=idenMap,
    actInd=actv,
    Solver=PardisoSolver
)
# G_grav = np.load('./G_Grav_Inverse.npy')
# prob._G = G_grav
# Pair the survey and problem
survey.pair(prob)

# Add noise to the data and assign uncertainties
std = 0.0
survey.eps = 0.
# We add some random Gaussian noise
survey.makeSyntheticData(model, std=std)
survey.dobs = survey.dobs + survey.eps * np.random.randn(survey.dobs.shape[0])

io_utils.writeUBCgravityObservations(
    'GRAV_CoarseForward_DoubleContrast_Synthetic_data.obs', survey, survey.dobs
)
np.save('G_Grav_Inverse', prob.G)

Mesh.TensorMesh.writeModelUBC(
    mesh,
    'model_grav_inverse_mesh.den',
    actvMap * model
)
fig, ax = plt.subplots(1, 1, figsize=(6, 6))
d2D = survey.dobs.reshape(X.shape)
dat = ax.contourf(X - xc, Y - yc, d2D, 40)
ax.set_aspect('equal')
ax.plot(X.flatten() - xc, Y.flatten() - yc, 'k.', ms=2)
plt.colorbar(dat)
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.set_title("Gz (mGal)")
ax.set_xlim(-500, 500)
ax.set_ylim(-500, 500)
fig.savefig('Grav_Data_Inverse_Mesh.png')
plt.show()
