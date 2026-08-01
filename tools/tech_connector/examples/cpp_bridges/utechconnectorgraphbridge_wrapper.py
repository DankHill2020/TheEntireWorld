# coding=utf-8
"""
    Python Wrapper for Reflected C++ Class `UTechConnectorGraphBridge`.
"""

import unreal

class UTechConnectorGraphBridgeWrapper:
	"""
	    Provides Python interface to native Unreal C++ feature `UTechConnectorGraphBridge`.
	"""

	@staticmethod
	def wireanimgraphposeoutput(AnimInstancePath, StateMachineName):
		"""
		    Invokes reflected C++ method `UTechConnectorGraphBridge.WireAnimGraphPoseOutput`.
		"""
		cpp_class = getattr(unreal, "UTechConnectorGraphBridge", None)
		if not cpp_class:
			raise RuntimeError("Native C++ class 'UTechConnectorGraphBridge' is not loaded in Unreal Python environment.")
		return cpp_class.wireanimgraphposeoutput(AnimInstancePath, StateMachineName)

	@staticmethod
	def injectcharactermovementnode(CharacterBPPath, InputKey):
		"""
		    Invokes reflected C++ method `UTechConnectorGraphBridge.InjectCharacterMovementNode`.
		"""
		cpp_class = getattr(unreal, "UTechConnectorGraphBridge", None)
		if not cpp_class:
			raise RuntimeError("Native C++ class 'UTechConnectorGraphBridge' is not loaded in Unreal Python environment.")
		return cpp_class.injectcharactermovementnode(CharacterBPPath, InputKey)
