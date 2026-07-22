// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

// IWYU pragma: private, include "AIStudioBridgeLibrary.h"

#ifdef AISTUDIOBRIDGE_AIStudioBridgeLibrary_generated_h
#error "AIStudioBridgeLibrary.generated.h already included, missing '#pragma once' in AIStudioBridgeLibrary.h"
#endif
#define AISTUDIOBRIDGE_AIStudioBridgeLibrary_generated_h

#include "UObject/ObjectMacros.h"
#include "UObject/ReflectedTypeAccessors.h"
#include "UObject/ScriptMacros.h"

PRAGMA_DISABLE_DEPRECATION_WARNINGS
class UAnimBlueprint;
class UAnimMontage;
class UAnimSequence;
class UBlueprint;
class UClass;
class UObject;
struct FKey;

// ********** Begin Class UAIStudioBridgeLibrary ***************************************************
#define FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_RPC_WRAPPERS_NO_PURE_DECLS \
	DECLARE_FUNCTION(execDescribeBlueprintNodeAction); \
	DECLARE_FUNCTION(execInjectKeyInPIE); \
	DECLARE_FUNCTION(execValidateCharacterMontagesInPIE); \
	DECLARE_FUNCTION(execInspectCharacterInPIE); \
	DECLARE_FUNCTION(execInspectAnimationSequence); \
	DECLARE_FUNCTION(execInspectAnimBlueprintGraph);


struct Z_Construct_UClass_UAIStudioBridgeLibrary_Statics;
AISTUDIOBRIDGE_API UClass* Z_Construct_UClass_UAIStudioBridgeLibrary(ETypeConstructPhase);

#define FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_INCLASS_NO_PURE_DECLS \
private: \
	friend struct ::Z_Construct_UClass_UAIStudioBridgeLibrary_Statics; \
	friend AISTUDIOBRIDGE_API UClass* ::Z_Construct_UClass_UAIStudioBridgeLibrary(ETypeConstructPhase); \
public: \
	DECLARE_CLASS2(UAIStudioBridgeLibrary, UBlueprintFunctionLibrary, COMPILED_IN_FLAGS(0), CASTCLASS_None, TEXT("/Script/AIStudioBridge"), Z_Construct_UClass_UAIStudioBridgeLibrary) \
	DECLARE_SERIALIZER(UAIStudioBridgeLibrary)


#define FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_ENHANCED_CONSTRUCTORS \
	/** Standard constructor, called after all reflected properties have been initialized */ \
	NO_API UAIStudioBridgeLibrary(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get()); \
	/** Deleted move- and copy-constructors, should never be used */ \
	UAIStudioBridgeLibrary(UAIStudioBridgeLibrary&&) = delete; \
	UAIStudioBridgeLibrary(const UAIStudioBridgeLibrary&) = delete; \
	DECLARE_VTABLE_PTR_HELPER_CTOR(NO_API, UAIStudioBridgeLibrary); \
	DEFINE_VTABLE_PTR_HELPER_CTOR_CALLER(UAIStudioBridgeLibrary); \
	DEFINE_DEFAULT_OBJECT_INITIALIZER_CONSTRUCTOR_CALL(UAIStudioBridgeLibrary) \
	NO_API virtual ~UAIStudioBridgeLibrary();


#define FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_11_PROLOG
#define FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_GENERATED_BODY \
PRAGMA_DISABLE_DEPRECATION_WARNINGS \
public: \
	FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_RPC_WRAPPERS_NO_PURE_DECLS \
	FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_INCLASS_NO_PURE_DECLS \
	FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h_14_ENHANCED_CONSTRUCTORS \
private: \
PRAGMA_ENABLE_DEPRECATION_WARNINGS


class UAIStudioBridgeLibrary;

// ********** End Class UAIStudioBridgeLibrary *****************************************************

#undef CURRENT_FILE_ID
#define CURRENT_FILE_ID FID_depot_tools_plugin_build_output_AIStudioBridge_20260720_2215_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h

PRAGMA_ENABLE_DEPRECATION_WARNINGS
