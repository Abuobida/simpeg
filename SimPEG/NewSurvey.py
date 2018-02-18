from __future__ import print_function

import numpy as np
import scipy.sparse as sp
import uuid
import gc
import properties

from . import Utils
from . import Props


class RxLocationArray(properties.Array):

    class_info = "an array of receiver locations"

    def validate(self, instance, value):
        if len(value.shape) == 1:
            value = Utils.mkvc(value, 2).T
        return super(RxLocationArray, self).validate(instance, value)


class BaseRx(properties.HasProperties):
    """SimPEG Receiver Object"""

    # TODO: write a validator that checks against mesh dimension in the
    # BaseSimulation
    locs = RxLocationArray(
        "Locations of the receivers (nRx x nDim)",
        shape=("*", "*"),
        required=True
    )

    # TODO: get rid of this
    # knownRxTypes = properties.String(
    #     "Set this to a list of strings to ensure that srcType is known",
    # )

    projGLoc = properties.StringChoice(
        "Projection grid location, default is CC",
        choices=["CC", "F", "E"],
        default="CC"
    )

    storeProjections = properties.Bool(
        "Store calls to getP (organized by mesh)",
        default=True
    )

    uid = properties.Uuid(
        "unique ID for the receiver"
    )

    _Ps = properties.Instance(
        "dictonary for storing projections",
        dict,
        default={}
    )

    # @property
    # def rxType(self):
    #     """Receiver Type"""
    #     return getattr(self, '_rxType', None)

    # @rxType.setter
    # def rxType(self, value):
    #     known = self.knownRxTypes
    #     if known is not None:
    #         assert value in known, (
    #             "rxType must be in ['{0!s}']".format(("', '".join(known)))
    #         )
    #     self._rxType = value

    @property
    def nD(self):
        """Number of data in the receiver."""
        return self.locs.shape[0]

    def getP(self, mesh, projGLoc=None):
        """
            Returns the projection matrices as a
            list for all components collected by
            the receivers.

            .. note::

                Projection matrices are stored as a dictionary listed by meshes.
        """
        if projGLoc is None:
            projGLoc = self.projGLoc

        if (mesh, projGLoc) in self._Ps:
            return self._Ps[(mesh, projGLoc)]

        P = mesh.getInterpolationMat(self.locs, projGLoc)
        if self.storeProjections:
            self._Ps[(mesh, projGLoc)] = P
        return P


class BaseTimeRx(BaseRx):
    """SimPEG Receiver Object for time-domain simulations"""

    times = properties.Array(
        "times where the recievers measure data",
        shape=("*",),
        required=True
    )

    projTLoc = properties.StringChoice(
        "location on the time mesh where the data are projected from",
        choices=["N", "CC"],
        default="N"
    )

    # def __init__(self, locs, times, rxType, **kwargs):
    #     self.times = times
    #     BaseRx.__init__(self, locs, rxType, **kwargs)

    @property
    def nD(self):
        """Number of data in the receiver."""
        return self.locs.shape[0] * len(self.times)

    def getSpatialP(self, mesh):
        """
            Returns the spatial projection matrix.

            .. note::

                This is not stored in memory, but is created on demand.
        """
        return mesh.getInterpolationMat(self.locs, self.projGLoc)

    def getTimeP(self, timeMesh):
        """
            Returns the time projection matrix.

            .. note::

                This is not stored in memory, but is created on demand.
        """
        return timeMesh.getInterpolationMat(self.times, self.projTLoc)

    def getP(self, mesh, timeMesh):
        """
            Returns the projection matrices as a
            list for all components collected by
            the receivers.

            .. note::

                Projection matrices are stored as a dictionary (mesh, timeMesh)
                if storeProjections is True
        """
        if (mesh, timeMesh) in self._Ps:
            return self._Ps[(mesh, timeMesh)]

        Ps = self.getSpatialP(mesh)
        Pt = self.getTimeP(timeMesh)
        P = sp.kron(Pt, Ps)

        if self.storeProjections:
            self._Ps[(mesh, timeMesh)] = P

        return P


class BaseSrc(Props.BaseSimPEG):
    """SimPEG Source Object"""

    loc = properties.Array(
        "Location [x, y, z]",
        shape=("*",)
    )

    rxList = properties.List(
        "receiver list",
        properties.Instance(
            "a SimPEG receiver",
            BaseRx
        ),
        default=[]
    )

    uid = properties.Uuid(
        "unique identifier for the source"
    )

    @properties.validator('rxList')
    def _rxList_validator(self, change):
        value = change['value']
        assert len(set(value)) == len(value), 'The rxList must be unique'
        self._rxOrder = dict()
        [
            self._rxOrder.setdefault(rx.uid, ii) for ii, rx in
            enumerate(value)
        ]

    def getReceiverIndex(self, receiver):
        if type(receiver) is not list:
            receiver = [receiver]
        for rx in receiver:
            if getattr(rx, 'uid', None) is None:
                raise KeyError(
                    'Source does not have a uid: {0!s}'.format(str(rx))
                )
        inds = list(map(
            lambda rx: self._rxOrder.get(rx.uid, None), receiver
        ))
        if None in inds:
            raise KeyError(
                'Some of the receiver specified are not in this survey. '
                '{0!s}'.format(str(inds))
            )
        return inds

    @property
    def nD(self):
        """Number of data"""
        return self.vnD.sum()

    @property
    def vnD(self):
        """Vector number of data"""
        return np.array([rx.nD for rx in self.rxList])


# TODO: allow a reciever list to be provided and assume it is used for all
# sources (and store the projections)
class BaseSurvey(properties.HasProperties):
    """
    Survey holds the sources and receivers for a survey
    """

    counter = properties.Instance(
        "A SimPEG counter object",
        Utils.Counter
    )

    srcList = properties.List(
        "A list of sources for the survey",
        properties.Instance(
            "A SimPEG source",
            BaseSrc
        ),
        required=True
    )

    def __init__(self, **kwargs):
        super(BaseSurvey, self).__init__(**kwargs)

    @properties.validator('srcList')
    def _srcList_validator(self, change):
        value = change['value']
        assert len(set(value)) == len(value), 'The srcList must be unique'
        self._sourceOrder = dict()
        [
            self._sourceOrder.setdefault(src.uid, ii) for ii, src in
            enumerate(value)
        ]

    def getSourceIndex(self, sources):
        if type(sources) is not list:
            sources = [sources]

        for src in sources:
            if getattr(src, 'uid', None) is None:
                raise KeyError(
                    'Source does not have a uid: {0!s}'.format(str(src))
                )
        inds = list(map(
            lambda src: self._sourceOrder.get(src.uid, None), sources
        ))
        if None in inds:
            raise KeyError(
                'Some of the sources specified are not in this survey. '
                '{0!s}'.format(str(inds))
            )
        return inds

    @property
    def nD(self):
        """Number of data"""
        return self.vnD.sum()

    @property
    def vnD(self):
        """Vector number of data"""
        return np.array([src.nD for src in self.srcList])

    @property
    def nSrc(self):
        """Number of Sources"""
        return len(self.srcList)

    def dpred(self, m, f=None):
        raise Exception(
            "Survey no longer has the dpred method. Please use "
            "simulation.dpred instead"
        )


# class LinearSurvey(BaseSurvey):
#     """
#     Survey for a linear problem
#     """
#     @property
#     def nD(self):
#         return self.simulation.G.shape[0]