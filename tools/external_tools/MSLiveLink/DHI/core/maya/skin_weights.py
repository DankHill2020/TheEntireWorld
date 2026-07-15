# Copyright Epic Games, Inc. All Rights Reserved.


class MayaSkinWeights:
    """
    Represents Maya mesh skin weights.

    It can represent 3 different skinning methods:
    METHOD_CLASSIC_LINEAR: Linear skinning method.

    Attributes:
        noOfInfluences (int): Maximum number of joint influences per vertex.
        skinningMethod (int): Skinning method.
        joints (string[]): List of strings representing influence object names.
        verticesInfo (float[][]): Float matrix representing influences per vertex.
            verticesInfo[i][j]:
            i: Represents vertex id. Each vertex has its own row.
            j: Each row is made of list of numbers. Odd numbers represents
                influence object index (int). Even numbers represent influence
                weight of previous influence object (float).
    """

    METHOD_CLASSIC_LINEAR = 0

    def __init__(self):
        self.noOfInfluences = 0  # (int)
        self.skinningMethod = MayaSkinWeights.METHOD_CLASSIC_LINEAR
        self.joints = []  # (string[])
        self.verticesInfo = []  # (float[][])

    def copy(self):
        """
        Makes deep copy of a MayaSkinWeights object and all of its inner data.

        @return Copy of self. (MayaJointDataHolder)
        """

        newSW = MayaSkinWeights()
        newSW.noOfInfluences = self.noOfInfluences
        newSW.skinningMethod = self.skinningMethod
        newSW.joints = self.joints[:]
        newSW.verticesInfo = [vi[:] for vi in self.verticesInfo]
        return newSW

    def getWeightsMatrix(self):
        """
        Converts MayaSkinWeights.verticesInfo data into [nVertices, nJoints] list of lists.
        First index (rows) represents vertex id number, while second index (columns) represents
        joint number. (weights[vtxId][jntId])

        @return Matrix containing skin weights. (float[nVerts, nJoints])
        """

        number_of_vertices = len(self.verticesInfo)
        number_of_joints = len(self.joints)
        weights = [[] for i in range(number_of_vertices)]

        for vertex_id, vtxInfo in enumerate(self.verticesInfo):
            vertex_weights = [0.0 for i in range(number_of_joints)]
            for inW in range(0, len(vtxInfo), 2):
                vertex_weights[vtxInfo[inW]] = vtxInfo[inW + 1]
            weights[vertex_id] = vertex_weights

        return weights

    def getInfluenceNamesMap(self, threshold=0.000001):
        """
        Returns influence map of this skin.

        @return List of sets of influence indices (int) for every vertex. ([set(int[])])
        """

        return [
            {self.joints[vertexInfo[i]] for i in range(0, len(vertexInfo), 2) if vertexInfo[i + 1] > threshold}
            for vertexInfo in self.verticesInfo
        ]
