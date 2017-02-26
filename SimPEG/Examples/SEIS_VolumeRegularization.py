import numpy as np
import scipy.sparse as sp
import properties
import matplotlib.pyplot as plt

from SimPEG.SEIS import StraightRay
from SimPEG import (
    Mesh, Maps, Utils, Regularization, Optimization,
    InvProblem, Inversion, DataMisfit, Directives, ObjectiveFunction
)


class Volume(ObjectiveFunction.BaseObjectiveFunction):

    """
    A regularization on the volume integral of the model

    .. math::

        \phi_v = \frac{1}{2}|| \int_V m dV - \text{knownVolume} ||^2
    """

    knownVolume = properties.Float("known volume", default=0., min=0.)

    def __init__(self, mesh, **kwargs):
        self.mesh = mesh
        super(Volume, self).__init__(**kwargs)

    def __call__(self, m):
        return 0.5*(self.estVol(m) - self.knownVolume)**2

    def estVol(self, m):
        return np.inner(self.mesh.vol, m)

    def deriv(self, m):
        # return (self.mesh.vol * np.inner(self.mesh.vol, m))
        return self.mesh.vol * (self.knownVolume - np.inner(self.mesh.vol, m))

    def deriv2(self, m, v=None):
        if v is not None:
            return Utils.mkvc(self.mesh.vol * np.inner(self.mesh.vol , v))
        else:
            # TODO: this is inefficent. It is a fully dense matrix
            return sp.csc_matrix(np.outer(self.mesh.vol, self.mesh.vol))


def run(plotIt=True, phi0=0, phi1=0.02):
    """
        Straight Ray with Volume Regularization
        =======================================

        Based on the SEG abstract Heagy, Cockett and Oldenburg, 2014.

        This example is a simple joint inversion that consists of a

            - data misfit for the tomography problem
            - data misfit for the volume of the inclusions
              (uses the effective medium theory mapping)
            - model regularization

    """
    nC = 40
    de = 1.
    h  = np.ones(nC)*de/nC
    M = Mesh.TensorMesh([h, h])

    y = np.linspace(M.vectorCCy[0], M.vectorCCx[-1], int(np.floor(nC/4)))
    rlocs = np.c_[0*y+M.vectorCCx[-1], y]
    rx = StraightRay.Rx(rlocs, None)

    srcList = [
        StraightRay.Src(loc=np.r_[M.vectorCCx[0], yi], rxList=[rx]) for yi in y
    ]

    # phi model
    phi0 = 0
    phi1 = 0.8
    phitrue = Utils.ModelBuilder.defineBlock(M.gridCC, [0.4, 0.6], [0.6, 0.4], [phi1, phi0])

    knownVolume = np.sum(phitrue*M.vol)
    print('True Volume: {}'.format(knownVolume))

    if plotIt:
        fig, ax = plt.subplots(1, 1)
        plt.colorbar(M.plotImage(phitrue, ax=ax)[0], ax=ax)
        ax.set_title('True $\phi$ Model')
        ax.set_ylabel('z')

    # Set up true conductivity model and plot the model transform
    sigma0 = np.exp(1)
    sigma1 = 1e3

    if plotIt:
        fig, ax = plt.subplots(1, 1)
        sigmaMapTest = Maps.SelfConsistentEffectiveMedium(
            nP=1000, sigma0=sigma0, sigma1=sigma1, rel_tol=1e-2
        )
        testphis = np.linspace(0., 1., 1000)

        sigetest = sigmaMapTest * testphis
        ax.semilogy(testphis, sigetest)
        ax.set_title('Model Transform')

    sigmaMap = Maps.SelfConsistentEffectiveMedium(
        M, sigma0=sigma0, sigma1=sigma1
    )

    # scale the slowness so it is on a ~linear scale
    slownessMap = Maps.LogMap(M) *  sigmaMap

    # set up the true sig model and log model dobs
    sigtrue = sigmaMap * phitrue

    # modt = Model.BaseModel(M);
    slownesstrue   = slownessMap * phitrue # true model (m = log(sigma))

    # set up the problem and survey
    survey = StraightRay.Survey(srcList)
    problem = StraightRay.Problem(M, slownessMap=slownessMap)
    problem.pair(survey)

    if plotIt:
        fig, ax = plt.subplots(1, 1)
        cb = plt.colorbar(M.plotImage(slownesstrue, ax=ax)[0], ax=ax)
        survey.plot(ax=ax)
        cb.set_label('slowness')

    # get observed data
    dobs = survey.makeSyntheticData(phitrue, std=0.03, force=True)
    dpred = survey.dpred(np.zeros(M.nC))

    if plotIt:
        fig, ax = plt.subplots(1, 1)
        ax.plot(dobs)
        ax.plot(dpred)
        ax.legend(['dobs', 'dpred0'])

    # objective function pieces
    reg = Regularization.Tikhonov(M)
    dmis = DataMisfit.l2_DataMisfit(survey)
    dmisVol = Volume(mesh=M, knownVolume=knownVolume)
    beta = 4e-2

    # without the volume regularization
    opt = Optimization.ProjectedGNCG(maxIter=4, lower=0.0, upper=1.0)
    opt.remember('xc')
    invProb = InvProblem.BaseInvProblem(dmis, reg, opt, beta=beta)
    # targetMisfit = Directives.TargetMisfit()
    inv = Inversion.BaseInversion(invProb)

    mopt1 = inv.run(np.zeros(M.nC)+1e-16)
    print(
        '\nTotal recovered volume (no vol misfit term in inversion): {}'.format(
            dmisVol(mopt1)
        )
    )

    # with the volume regularization
    vol_multiplier = 6e5
    reg2 = reg
    dmis2 = dmis + vol_multiplier * dmisVol
    opt2 = Optimization.ProjectedGNCG(maxIter=4, lower=0.0, upper=1.0)
    opt2.remember('xc')
    invProb2 = InvProblem.BaseInvProblem(dmis2, reg2, opt2, beta=beta)
    # targetMisfit = Directives.TargetMisfit()
    inv2 = Inversion.BaseInversion(invProb2)

    mopt2 = inv2.run(np.zeros(M.nC)+1e-16)
    print(
        '\nTotal volume (vol misfit term in inversion): {}'.format(
            dmisVol(mopt2)
        )
    )

    # plot results

    if plotIt:
        fig, ax = plt.subplots(1, 3, figsize=(12, 4))

        cb0 = plt.colorbar(M.plotImage(phitrue, ax=ax[0])[0], ax=ax[0])
        cb1 = plt.colorbar(M.plotImage(mopt1, ax=ax[1])[0], ax=ax[1])
        cb2 = plt.colorbar(M.plotImage(mopt2, ax=ax[2])[0], ax=ax[2])

        for cb in [cb0, cb1, cb2]:
            cb.set_clim([0., phi1])

        ax[0].set_title('true, vol: {:1.3e}'.format(knownVolume))
        ax[1].set_title(
            'recovered(no Volume term), vol: {:1.3e} '.format(dmisVol(mopt1))
        )
        ax[2].set_title(
            'recovered(with Volume term), vol: {:1.3e} '.format(dmisVol(mopt2))
        )

        plt.tight_layout()

if __name__ == '__main__':
    run()
    plt.show()
