// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

#include "UObject/GeneratedCppIncludes.h"
#include "AIStudioBridgeLibrary.h"
#include "InputCoreTypes.h"
#include "UObject/Class.h"

PRAGMA_DISABLE_DEPRECATION_WARNINGS
static_assert(!UE_WITH_CONSTINIT_UOBJECT, "This generated code can only be compiled with !UE_WITH_CONSTINIT_UOBJECT");
void EmptyLinkFunctionForGeneratedCodeAIStudioBridgeLibrary() {}

// ********** Begin Cross Module References ********************************************************
ENGINE_API UClass* Z_Construct_UClass_UBlueprintFunctionLibrary(ETypeConstructPhase);
INPUTCORE_API UScriptStruct* Z_Construct_UScriptStruct_FKey(ETypeConstructPhase);
COREUOBJECT_API UClass* Z_Construct_UClass_UClass(ETypeConstructPhase);
COREUOBJECT_API UClass* Z_Construct_UClass_UObject(ETypeConstructPhase);
ENGINE_API UClass* Z_Construct_UClass_UAnimBlueprint(ETypeConstructPhase);
ENGINE_API UClass* Z_Construct_UClass_UAnimMontage(ETypeConstructPhase);
ENGINE_API UClass* Z_Construct_UClass_UAnimSequence(ETypeConstructPhase);
ENGINE_API UClass* Z_Construct_UClass_UBlueprint(ETypeConstructPhase);
// ********** End Cross Module References **********************************************************

// ********** Begin Same Module References *********************************************************
UPackage* Z_Construct_UPackage__Script_AIStudioBridge(ETypeConstructPhase);
AISTUDIOBRIDGE_API UClass* Z_Construct_UClass_UAIStudioBridgeLibrary(ETypeConstructPhase);
AISTUDIOBRIDGE_API UClass* Z_Construct_UClass_UAIStudioBridgeLibrary(ETypeConstructPhase);
// ********** End Same Module References ***********************************************************
#define UHT_STRUCT_BASE(INIT) UE::CodeGen::ConstInit::TCompiledInObjectPtr<const FStructBaseChain>(UE::Private::AsStructBaseChain(INIT))

// ********** Begin Class UAIStudioBridgeLibrary Function AddAnimGraphState ************************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_AddAnimGraphState_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventAddAnimGraphState_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName StateName;
		UObject* AnimationAsset;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function AddAnimGraphState constinit property declarations *********************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateName;
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimationAsset;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function AddAnimGraphState constinit property declarations ***********************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function AddAnimGraphState Property Definitions ********************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphState_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphState_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateName = { "StateName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphState_Parms, StateName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimationAsset = { "AnimationAsset", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphState_Parms, AnimationAsset), Z_Construct_UClass_UObject, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphState_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimationAsset,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function AddAnimGraphState Property Definitions **********************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "AddAnimGraphState", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventAddAnimGraphState_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventAddAnimGraphState_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_AddAnimGraphState(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execAddAnimGraphState)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateName);
	P_GET_OBJECT(UObject,Z_Param_AnimationAsset);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::AddAnimGraphState(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_StateName,Z_Param_AnimationAsset);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function AddAnimGraphState **************************

// ********** Begin Class UAIStudioBridgeLibrary Function AddAnimGraphTransitionRule ***************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_AddAnimGraphTransitionRule_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName FromState;
		FName ToState;
		FString RuleExpression;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_RuleExpression_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function AddAnimGraphTransitionRule constinit property declarations ************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_FromState;
	static const UECodeGen_Private::FNamePropertyParams NewProp_ToState;
	static const UECodeGen_Private::FStrPropertyParams NewProp_RuleExpression;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function AddAnimGraphTransitionRule constinit property declarations **************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function AddAnimGraphTransitionRule Property Definitions ***********************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_FromState = { "FromState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms, FromState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_ToState = { "ToState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms, ToState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_RuleExpression = { "RuleExpression", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms, RuleExpression), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_RuleExpression_MetaData), NewProp_RuleExpression_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FromState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ToState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_RuleExpression,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function AddAnimGraphTransitionRule Property Definitions *************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "AddAnimGraphTransitionRule", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventAddAnimGraphTransitionRule_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_AddAnimGraphTransitionRule(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execAddAnimGraphTransitionRule)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_FromState);
	P_GET_PROPERTY(FNameProperty,Z_Param_ToState);
	P_GET_PROPERTY(FStrProperty,Z_Param_RuleExpression);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::AddAnimGraphTransitionRule(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_FromState,Z_Param_ToState,Z_Param_RuleExpression);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function AddAnimGraphTransitionRule *****************

// ********** Begin Class UAIStudioBridgeLibrary Function AddObjectReferenceToReflectedArray *******
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_AddObjectReferenceToReflectedArray_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms
	{
		FString AssetPath;
		FName PropertyName;
		FString ObjectPath;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Domain" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_AssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ObjectPath_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function AddObjectReferenceToReflectedArray constinit property declarations ****
	static const UECodeGen_Private::FStrPropertyParams NewProp_AssetPath;
	static const UECodeGen_Private::FNamePropertyParams NewProp_PropertyName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ObjectPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function AddObjectReferenceToReflectedArray constinit property declarations ******
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function AddObjectReferenceToReflectedArray Property Definitions ***************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_AssetPath = { "AssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms, AssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_AssetPath_MetaData), NewProp_AssetPath_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_PropertyName = { "PropertyName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms, PropertyName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ObjectPath = { "ObjectPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms, ObjectPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ObjectPath_MetaData), NewProp_ObjectPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ObjectPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function AddObjectReferenceToReflectedArray Property Definitions *****************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "AddObjectReferenceToReflectedArray", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventAddObjectReferenceToReflectedArray_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_AddObjectReferenceToReflectedArray(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execAddObjectReferenceToReflectedArray)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_AssetPath);
	P_GET_PROPERTY(FNameProperty,Z_Param_PropertyName);
	P_GET_PROPERTY(FStrProperty,Z_Param_ObjectPath);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::AddObjectReferenceToReflectedArray(Z_Param_AssetPath,Z_Param_PropertyName,Z_Param_ObjectPath);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function AddObjectReferenceToReflectedArray *********

// ********** Begin Class UAIStudioBridgeLibrary Function BindNiagaraUserParametersOnBeginPlay *****
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_BindNiagaraUserParametersOnBeginPlay_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms
	{
		UBlueprint* Blueprint;
		TArray<FName> ComponentNames;
		FString BindingsJson;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Niagara" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ComponentNames_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BindingsJson_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function BindNiagaraUserParametersOnBeginPlay constinit property declarations **
	static const UECodeGen_Private::FObjectPropertyParams NewProp_Blueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_ComponentNames_Inner;
	static const UECodeGen_Private::FArrayPropertyParams NewProp_ComponentNames;
	static const UECodeGen_Private::FStrPropertyParams NewProp_BindingsJson;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function BindNiagaraUserParametersOnBeginPlay constinit property declarations ****
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function BindNiagaraUserParametersOnBeginPlay Property Definitions *************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_Blueprint = { "Blueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms, Blueprint), Z_Construct_UClass_UBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_ComponentNames_Inner = { "ComponentNames", nullptr, (EPropertyFlags)0x0000000000000000, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, 0, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FArrayPropertyParams UHT_STATICS::NewProp_ComponentNames = { "ComponentNames", nullptr, (EPropertyFlags)0x0010000008000182, UECodeGen_Private::EPropertyGenFlags::Array, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms, ComponentNames), EArrayPropertyFlags::None, METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ComponentNames_MetaData), NewProp_ComponentNames_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BindingsJson = { "BindingsJson", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms, BindingsJson), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BindingsJson_MetaData), NewProp_BindingsJson_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Blueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ComponentNames_Inner,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ComponentNames,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BindingsJson,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function BindNiagaraUserParametersOnBeginPlay Property Definitions ***************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "BindNiagaraUserParametersOnBeginPlay", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04422401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventBindNiagaraUserParametersOnBeginPlay_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_BindNiagaraUserParametersOnBeginPlay(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execBindNiagaraUserParametersOnBeginPlay)
{
	P_GET_OBJECT(UBlueprint,Z_Param_Blueprint);
	P_GET_TARRAY_REF(FName,Z_Param_Out_ComponentNames);
	P_GET_PROPERTY(FStrProperty,Z_Param_BindingsJson);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::BindNiagaraUserParametersOnBeginPlay(Z_Param_Blueprint,Z_Param_Out_ComponentNames,Z_Param_BindingsJson);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function BindNiagaraUserParametersOnBeginPlay *******

// ********** Begin Class UAIStudioBridgeLibrary Function CompileAndSaveAnimBlueprint **************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_CompileAndSaveAnimBlueprint_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventCompileAndSaveAnimBlueprint_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function CompileAndSaveAnimBlueprint constinit property declarations ***********
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function CompileAndSaveAnimBlueprint constinit property declarations *************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function CompileAndSaveAnimBlueprint Property Definitions **********************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventCompileAndSaveAnimBlueprint_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventCompileAndSaveAnimBlueprint_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function CompileAndSaveAnimBlueprint Property Definitions ************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "CompileAndSaveAnimBlueprint", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventCompileAndSaveAnimBlueprint_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventCompileAndSaveAnimBlueprint_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_CompileAndSaveAnimBlueprint(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execCompileAndSaveAnimBlueprint)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::CompileAndSaveAnimBlueprint(Z_Param_AnimBlueprint);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function CompileAndSaveAnimBlueprint ****************

// ********** Begin Class UAIStudioBridgeLibrary Function CreateKnownAssetByClassPath **************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_CreateKnownAssetByClassPath_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms
	{
		FString AssetPath;
		FString ClassPath;
		FString InitialPropertiesJson;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Domain" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_AssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ClassPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_InitialPropertiesJson_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function CreateKnownAssetByClassPath constinit property declarations ***********
	static const UECodeGen_Private::FStrPropertyParams NewProp_AssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ClassPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_InitialPropertiesJson;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function CreateKnownAssetByClassPath constinit property declarations *************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function CreateKnownAssetByClassPath Property Definitions **********************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_AssetPath = { "AssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms, AssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_AssetPath_MetaData), NewProp_AssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ClassPath = { "ClassPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms, ClassPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ClassPath_MetaData), NewProp_ClassPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_InitialPropertiesJson = { "InitialPropertiesJson", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms, InitialPropertiesJson), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_InitialPropertiesJson_MetaData), NewProp_InitialPropertiesJson_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ClassPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_InitialPropertiesJson,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function CreateKnownAssetByClassPath Property Definitions ************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "CreateKnownAssetByClassPath", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventCreateKnownAssetByClassPath_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_CreateKnownAssetByClassPath(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execCreateKnownAssetByClassPath)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_AssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_ClassPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_InitialPropertiesJson);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::CreateKnownAssetByClassPath(Z_Param_AssetPath,Z_Param_ClassPath,Z_Param_InitialPropertiesJson);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function CreateKnownAssetByClassPath ****************

// ********** Begin Class UAIStudioBridgeLibrary Function DeleteAnimGraphState *********************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_DeleteAnimGraphState_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName StateName;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function DeleteAnimGraphState constinit property declarations ******************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function DeleteAnimGraphState constinit property declarations ********************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function DeleteAnimGraphState Property Definitions *****************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateName = { "StateName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms, StateName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function DeleteAnimGraphState Property Definitions *******************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "DeleteAnimGraphState", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventDeleteAnimGraphState_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_DeleteAnimGraphState(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execDeleteAnimGraphState)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateName);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::DeleteAnimGraphState(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_StateName);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function DeleteAnimGraphState ***********************

// ********** Begin Class UAIStudioBridgeLibrary Function DeleteAnimGraphTransition ****************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_DeleteAnimGraphTransition_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName FromState;
		FName ToState;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function DeleteAnimGraphTransition constinit property declarations *************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_FromState;
	static const UECodeGen_Private::FNamePropertyParams NewProp_ToState;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function DeleteAnimGraphTransition constinit property declarations ***************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function DeleteAnimGraphTransition Property Definitions ************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_FromState = { "FromState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms, FromState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_ToState = { "ToState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms, ToState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FromState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ToState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function DeleteAnimGraphTransition Property Definitions **************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "DeleteAnimGraphTransition", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventDeleteAnimGraphTransition_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_DeleteAnimGraphTransition(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execDeleteAnimGraphTransition)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_FromState);
	P_GET_PROPERTY(FNameProperty,Z_Param_ToState);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::DeleteAnimGraphTransition(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_FromState,Z_Param_ToState);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function DeleteAnimGraphTransition ******************

// ********** Begin Class UAIStudioBridgeLibrary Function DescribeBlueprintNodeAction **************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_DescribeBlueprintNodeAction_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms
	{
		UBlueprint* Blueprint;
		FName GraphName;
		FString NodeWithCategory;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Blueprint" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_NodeWithCategory_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function DescribeBlueprintNodeAction constinit property declarations ***********
	static const UECodeGen_Private::FObjectPropertyParams NewProp_Blueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_NodeWithCategory;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function DescribeBlueprintNodeAction constinit property declarations *************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function DescribeBlueprintNodeAction Property Definitions **********************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_Blueprint = { "Blueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms, Blueprint), Z_Construct_UClass_UBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms, GraphName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_NodeWithCategory = { "NodeWithCategory", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms, NodeWithCategory), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_NodeWithCategory_MetaData), NewProp_NodeWithCategory_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Blueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_NodeWithCategory,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function DescribeBlueprintNodeAction Property Definitions ************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "DescribeBlueprintNodeAction", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventDescribeBlueprintNodeAction_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_DescribeBlueprintNodeAction(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execDescribeBlueprintNodeAction)
{
	P_GET_OBJECT(UBlueprint,Z_Param_Blueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_NodeWithCategory);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::DescribeBlueprintNodeAction(Z_Param_Blueprint,Z_Param_GraphName,Z_Param_NodeWithCategory);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function DescribeBlueprintNodeAction ****************

// ********** Begin Class UAIStudioBridgeLibrary Function InjectKeyInPIE ***************************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_InjectKeyInPIE_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms
	{
		FKey Key;
		bool bPressed;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Runtime" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function InjectKeyInPIE constinit property declarations ************************
	static const UECodeGen_Private::FStructPropertyParams NewProp_Key;
	static void NewProp_bPressed_SetBit(void* Obj)
	{
		((AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms*)Obj)->bPressed = 1;
	}
	static const UECodeGen_Private::FBoolPropertyParams NewProp_bPressed;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function InjectKeyInPIE constinit property declarations **************************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function InjectKeyInPIE Property Definitions ***********************************
const UECodeGen_Private::FStructPropertyParams UHT_STATICS::NewProp_Key = { "Key", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Struct, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms, Key), Z_Construct_UScriptStruct_FKey, METADATA_PARAMS(0, nullptr) }; // 64b3e4afc222613fc56ee34bd705dda53a3378d0
const UECodeGen_Private::FBoolPropertyParams UHT_STATICS::NewProp_bPressed = { "bPressed", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Bool | UECodeGen_Private::EPropertyGenFlags::NativeBool, nullptr, nullptr, 1, sizeof(bool), sizeof(AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms), &UHT_STATICS::NewProp_bPressed_SetBit, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Key,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_bPressed,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function InjectKeyInPIE Property Definitions *************************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "InjectKeyInPIE", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventInjectKeyInPIE_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_InjectKeyInPIE(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execInjectKeyInPIE)
{
	P_GET_STRUCT(FKey,Z_Param_Key);
	P_GET_UBOOL(Z_Param_bPressed);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::InjectKeyInPIE(Z_Param_Key,Z_Param_bPressed);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function InjectKeyInPIE *****************************

// ********** Begin Class UAIStudioBridgeLibrary Function InspectAnimationSequence *****************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimationSequence_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventInspectAnimationSequence_Parms
	{
		UAnimSequence* Animation;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function InspectAnimationSequence constinit property declarations **************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_Animation;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function InspectAnimationSequence constinit property declarations ****************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function InspectAnimationSequence Property Definitions *************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_Animation = { "Animation", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectAnimationSequence_Parms, Animation), Z_Construct_UClass_UAnimSequence, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectAnimationSequence_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Animation,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function InspectAnimationSequence Property Definitions ***************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "InspectAnimationSequence", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventInspectAnimationSequence_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventInspectAnimationSequence_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimationSequence(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execInspectAnimationSequence)
{
	P_GET_OBJECT(UAnimSequence,Z_Param_Animation);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::InspectAnimationSequence(Z_Param_Animation);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function InspectAnimationSequence *******************

// ********** Begin Class UAIStudioBridgeLibrary Function InspectAnimBlueprintGraph ****************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimBlueprintGraph_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventInspectAnimBlueprintGraph_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function InspectAnimBlueprintGraph constinit property declarations *************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function InspectAnimBlueprintGraph constinit property declarations ***************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function InspectAnimBlueprintGraph Property Definitions ************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectAnimBlueprintGraph_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectAnimBlueprintGraph_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function InspectAnimBlueprintGraph Property Definitions **************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "InspectAnimBlueprintGraph", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventInspectAnimBlueprintGraph_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventInspectAnimBlueprintGraph_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimBlueprintGraph(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execInspectAnimBlueprintGraph)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::InspectAnimBlueprintGraph(Z_Param_AnimBlueprint);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function InspectAnimBlueprintGraph ******************

// ********** Begin Class UAIStudioBridgeLibrary Function InspectCharacterInPIE ********************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectCharacterInPIE_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms
	{
		UClass* CharacterClass;
		FString ExpectedAnimClassContains;
		TArray<FName> PropertyNames;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Runtime" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_PropertyNames_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function InspectCharacterInPIE constinit property declarations *****************
	static const UECodeGen_Private::FClassPropertyParams NewProp_CharacterClass;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ExpectedAnimClassContains;
	static const UECodeGen_Private::FNamePropertyParams NewProp_PropertyNames_Inner;
	static const UECodeGen_Private::FArrayPropertyParams NewProp_PropertyNames;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function InspectCharacterInPIE constinit property declarations *******************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function InspectCharacterInPIE Property Definitions ****************************
const UECodeGen_Private::FClassPropertyParams UHT_STATICS::NewProp_CharacterClass = { "CharacterClass", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Class, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms, CharacterClass), Z_Construct_UClass_UClass, Z_Construct_UClass_UObject, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ExpectedAnimClassContains = { "ExpectedAnimClassContains", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms, ExpectedAnimClassContains), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_PropertyNames_Inner = { "PropertyNames", nullptr, (EPropertyFlags)0x0000000000000000, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, 0, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FArrayPropertyParams UHT_STATICS::NewProp_PropertyNames = { "PropertyNames", nullptr, (EPropertyFlags)0x0010000008000182, UECodeGen_Private::EPropertyGenFlags::Array, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms, PropertyNames), EArrayPropertyFlags::None, METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_PropertyNames_MetaData), NewProp_PropertyNames_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_CharacterClass,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ExpectedAnimClassContains,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyNames_Inner,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyNames,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function InspectCharacterInPIE Property Definitions ******************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "InspectCharacterInPIE", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04422401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventInspectCharacterInPIE_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectCharacterInPIE(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execInspectCharacterInPIE)
{
	P_GET_OBJECT(UClass,Z_Param_CharacterClass);
	P_GET_PROPERTY(FStrProperty,Z_Param_ExpectedAnimClassContains);
	P_GET_TARRAY_REF(FName,Z_Param_Out_PropertyNames);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::InspectCharacterInPIE(Z_Param_CharacterClass,Z_Param_ExpectedAnimClassContains,Z_Param_Out_PropertyNames);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function InspectCharacterInPIE **********************

// ********** Begin Class UAIStudioBridgeLibrary Function InspectReflectedAsset ********************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectReflectedAsset_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventInspectReflectedAsset_Parms
	{
		FString AssetPath;
		TArray<FName> PropertyNames;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Domain" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_AssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_PropertyNames_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function InspectReflectedAsset constinit property declarations *****************
	static const UECodeGen_Private::FStrPropertyParams NewProp_AssetPath;
	static const UECodeGen_Private::FNamePropertyParams NewProp_PropertyNames_Inner;
	static const UECodeGen_Private::FArrayPropertyParams NewProp_PropertyNames;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function InspectReflectedAsset constinit property declarations *******************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function InspectReflectedAsset Property Definitions ****************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_AssetPath = { "AssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectReflectedAsset_Parms, AssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_AssetPath_MetaData), NewProp_AssetPath_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_PropertyNames_Inner = { "PropertyNames", nullptr, (EPropertyFlags)0x0000000000000000, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, 0, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FArrayPropertyParams UHT_STATICS::NewProp_PropertyNames = { "PropertyNames", nullptr, (EPropertyFlags)0x0010000008000182, UECodeGen_Private::EPropertyGenFlags::Array, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectReflectedAsset_Parms, PropertyNames), EArrayPropertyFlags::None, METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_PropertyNames_MetaData), NewProp_PropertyNames_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventInspectReflectedAsset_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyNames_Inner,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyNames,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function InspectReflectedAsset Property Definitions ******************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "InspectReflectedAsset", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventInspectReflectedAsset_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04422401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventInspectReflectedAsset_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectReflectedAsset(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execInspectReflectedAsset)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_AssetPath);
	P_GET_TARRAY_REF(FName,Z_Param_Out_PropertyNames);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::InspectReflectedAsset(Z_Param_AssetPath,Z_Param_Out_PropertyNames);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function InspectReflectedAsset **********************

// ********** Begin Class UAIStudioBridgeLibrary Function RemoveObjectReferenceFromReflectedArray **
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_RemoveObjectReferenceFromReflectedArray_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms
	{
		FString AssetPath;
		FName PropertyName;
		FString ObjectPath;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Domain" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_AssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ObjectPath_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function RemoveObjectReferenceFromReflectedArray constinit property declarations 
	static const UECodeGen_Private::FStrPropertyParams NewProp_AssetPath;
	static const UECodeGen_Private::FNamePropertyParams NewProp_PropertyName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ObjectPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function RemoveObjectReferenceFromReflectedArray constinit property declarations *
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function RemoveObjectReferenceFromReflectedArray Property Definitions **********
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_AssetPath = { "AssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms, AssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_AssetPath_MetaData), NewProp_AssetPath_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_PropertyName = { "PropertyName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms, PropertyName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ObjectPath = { "ObjectPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms, ObjectPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ObjectPath_MetaData), NewProp_ObjectPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ObjectPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function RemoveObjectReferenceFromReflectedArray Property Definitions ************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "RemoveObjectReferenceFromReflectedArray", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventRemoveObjectReferenceFromReflectedArray_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_RemoveObjectReferenceFromReflectedArray(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execRemoveObjectReferenceFromReflectedArray)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_AssetPath);
	P_GET_PROPERTY(FNameProperty,Z_Param_PropertyName);
	P_GET_PROPERTY(FStrProperty,Z_Param_ObjectPath);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::RemoveObjectReferenceFromReflectedArray(Z_Param_AssetPath,Z_Param_PropertyName,Z_Param_ObjectPath);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function RemoveObjectReferenceFromReflectedArray ****

// ********** Begin Class UAIStudioBridgeLibrary Function RenameAnimGraphState *********************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_RenameAnimGraphState_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName OldStateName;
		FName NewStateName;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function RenameAnimGraphState constinit property declarations ******************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_OldStateName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_NewStateName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function RenameAnimGraphState constinit property declarations ********************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function RenameAnimGraphState Property Definitions *****************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_OldStateName = { "OldStateName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms, OldStateName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_NewStateName = { "NewStateName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms, NewStateName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_OldStateName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_NewStateName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function RenameAnimGraphState Property Definitions *******************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "RenameAnimGraphState", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventRenameAnimGraphState_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_RenameAnimGraphState(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execRenameAnimGraphState)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_OldStateName);
	P_GET_PROPERTY(FNameProperty,Z_Param_NewStateName);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::RenameAnimGraphState(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_OldStateName,Z_Param_NewStateName);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function RenameAnimGraphState ***********************

// ********** Begin Class UAIStudioBridgeLibrary Function SearchBlueprintNodeActions ***************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_SearchBlueprintNodeActions_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms
	{
		UBlueprint* Blueprint;
		FName GraphName;
		FString Query;
		int32 MaxResults;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Blueprint" },
		{ "CPP_Default_MaxResults", "50" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_Query_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function SearchBlueprintNodeActions constinit property declarations ************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_Blueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_Query;
	static const UECodeGen_Private::FIntPropertyParams NewProp_MaxResults;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function SearchBlueprintNodeActions constinit property declarations **************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function SearchBlueprintNodeActions Property Definitions ***********************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_Blueprint = { "Blueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms, Blueprint), Z_Construct_UClass_UBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms, GraphName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_Query = { "Query", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms, Query), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_Query_MetaData), NewProp_Query_MetaData) };
const UECodeGen_Private::FIntPropertyParams UHT_STATICS::NewProp_MaxResults = { "MaxResults", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Int, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms, MaxResults), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Blueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Query,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_MaxResults,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function SearchBlueprintNodeActions Property Definitions *************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "SearchBlueprintNodeActions", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventSearchBlueprintNodeActions_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_SearchBlueprintNodeActions(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execSearchBlueprintNodeActions)
{
	P_GET_OBJECT(UBlueprint,Z_Param_Blueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_Query);
	P_GET_PROPERTY(FIntProperty,Z_Param_MaxResults);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::SearchBlueprintNodeActions(Z_Param_Blueprint,Z_Param_GraphName,Z_Param_Query,Z_Param_MaxResults);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function SearchBlueprintNodeActions *****************

// ********** Begin Class UAIStudioBridgeLibrary Function SetAnimGraphTransitionRule ***************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_SetAnimGraphTransitionRule_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName FromState;
		FName ToState;
		FString RuleExpression;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_RuleExpression_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function SetAnimGraphTransitionRule constinit property declarations ************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_FromState;
	static const UECodeGen_Private::FNamePropertyParams NewProp_ToState;
	static const UECodeGen_Private::FStrPropertyParams NewProp_RuleExpression;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function SetAnimGraphTransitionRule constinit property declarations **************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function SetAnimGraphTransitionRule Property Definitions ***********************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_FromState = { "FromState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms, FromState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_ToState = { "ToState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms, ToState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_RuleExpression = { "RuleExpression", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms, RuleExpression), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_RuleExpression_MetaData), NewProp_RuleExpression_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FromState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ToState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_RuleExpression,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function SetAnimGraphTransitionRule Property Definitions *************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "SetAnimGraphTransitionRule", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventSetAnimGraphTransitionRule_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_SetAnimGraphTransitionRule(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execSetAnimGraphTransitionRule)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_FromState);
	P_GET_PROPERTY(FNameProperty,Z_Param_ToState);
	P_GET_PROPERTY(FStrProperty,Z_Param_RuleExpression);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::SetAnimGraphTransitionRule(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_FromState,Z_Param_ToState,Z_Param_RuleExpression);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function SetAnimGraphTransitionRule *****************

// ********** Begin Class UAIStudioBridgeLibrary Function SetReflectedAssetProperty ****************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_SetReflectedAssetProperty_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms
	{
		FString AssetPath;
		FName PropertyName;
		FString ValueJson;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Domain" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_AssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ValueJson_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function SetReflectedAssetProperty constinit property declarations *************
	static const UECodeGen_Private::FStrPropertyParams NewProp_AssetPath;
	static const UECodeGen_Private::FNamePropertyParams NewProp_PropertyName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ValueJson;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function SetReflectedAssetProperty constinit property declarations ***************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function SetReflectedAssetProperty Property Definitions ************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_AssetPath = { "AssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms, AssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_AssetPath_MetaData), NewProp_AssetPath_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_PropertyName = { "PropertyName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms, PropertyName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ValueJson = { "ValueJson", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms, ValueJson), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ValueJson_MetaData), NewProp_ValueJson_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PropertyName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ValueJson,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function SetReflectedAssetProperty Property Definitions **************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "SetReflectedAssetProperty", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventSetReflectedAssetProperty_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_SetReflectedAssetProperty(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execSetReflectedAssetProperty)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_AssetPath);
	P_GET_PROPERTY(FNameProperty,Z_Param_PropertyName);
	P_GET_PROPERTY(FStrProperty,Z_Param_ValueJson);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::SetReflectedAssetProperty(Z_Param_AssetPath,Z_Param_PropertyName,Z_Param_ValueJson);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function SetReflectedAssetProperty ******************

// ********** Begin Class UAIStudioBridgeLibrary Function SynthesizeAnimGraphTransitionRuleExpression 
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_SynthesizeAnimGraphTransitionRuleExpression_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FName FromState;
		FName ToState;
		FString RuleExpression;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_RuleExpression_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function SynthesizeAnimGraphTransitionRuleExpression constinit property declarations 
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FNamePropertyParams NewProp_FromState;
	static const UECodeGen_Private::FNamePropertyParams NewProp_ToState;
	static const UECodeGen_Private::FStrPropertyParams NewProp_RuleExpression;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function SynthesizeAnimGraphTransitionRuleExpression constinit property declarations 
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function SynthesizeAnimGraphTransitionRuleExpression Property Definitions ******
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_FromState = { "FromState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms, FromState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_ToState = { "ToState", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms, ToState), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_RuleExpression = { "RuleExpression", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms, RuleExpression), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_RuleExpression_MetaData), NewProp_RuleExpression_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FromState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ToState,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_RuleExpression,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function SynthesizeAnimGraphTransitionRuleExpression Property Definitions ********
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "SynthesizeAnimGraphTransitionRuleExpression", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventSynthesizeAnimGraphTransitionRuleExpression_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_SynthesizeAnimGraphTransitionRuleExpression(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execSynthesizeAnimGraphTransitionRuleExpression)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_GET_PROPERTY(FNameProperty,Z_Param_FromState);
	P_GET_PROPERTY(FNameProperty,Z_Param_ToState);
	P_GET_PROPERTY(FStrProperty,Z_Param_RuleExpression);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::SynthesizeAnimGraphTransitionRuleExpression(Z_Param_AnimBlueprint,Z_Param_StateMachineName,Z_Param_FromState,Z_Param_ToState,Z_Param_RuleExpression);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function SynthesizeAnimGraphTransitionRuleExpression 

// ********** Begin Class UAIStudioBridgeLibrary Function ValidateCharacterMontagesInPIE ***********
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_ValidateCharacterMontagesInPIE_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms
	{
		UClass* CharacterClass;
		TArray<UAnimMontage*> Montages;
		FString ExpectedAnimClassContains;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Runtime" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_Montages_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function ValidateCharacterMontagesInPIE constinit property declarations ********
	static const UECodeGen_Private::FClassPropertyParams NewProp_CharacterClass;
	static const UECodeGen_Private::FObjectPropertyParams NewProp_Montages_Inner;
	static const UECodeGen_Private::FArrayPropertyParams NewProp_Montages;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ExpectedAnimClassContains;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function ValidateCharacterMontagesInPIE constinit property declarations **********
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function ValidateCharacterMontagesInPIE Property Definitions *******************
const UECodeGen_Private::FClassPropertyParams UHT_STATICS::NewProp_CharacterClass = { "CharacterClass", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Class, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms, CharacterClass), Z_Construct_UClass_UClass, Z_Construct_UClass_UObject, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_Montages_Inner = { "Montages", nullptr, (EPropertyFlags)0x0000000000000000, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, 0, Z_Construct_UClass_UAnimMontage, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FArrayPropertyParams UHT_STATICS::NewProp_Montages = { "Montages", nullptr, (EPropertyFlags)0x0010000008000182, UECodeGen_Private::EPropertyGenFlags::Array, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms, Montages), EArrayPropertyFlags::None, METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_Montages_MetaData), NewProp_Montages_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ExpectedAnimClassContains = { "ExpectedAnimClassContains", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms, ExpectedAnimClassContains), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_CharacterClass,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Montages_Inner,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Montages,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ExpectedAnimClassContains,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function ValidateCharacterMontagesInPIE Property Definitions *********************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "ValidateCharacterMontagesInPIE", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04422401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventValidateCharacterMontagesInPIE_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_ValidateCharacterMontagesInPIE(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execValidateCharacterMontagesInPIE)
{
	P_GET_OBJECT(UClass,Z_Param_CharacterClass);
	P_GET_TARRAY_REF(UAnimMontage*,Z_Param_Out_Montages);
	P_GET_PROPERTY(FStrProperty,Z_Param_ExpectedAnimClassContains);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::ValidateCharacterMontagesInPIE(Z_Param_CharacterClass,Z_Param_Out_Montages,Z_Param_ExpectedAnimClassContains);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function ValidateCharacterMontagesInPIE *************

// ********** Begin Class UAIStudioBridgeLibrary Function WireAnimGraphOutputPose ******************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UAIStudioBridgeLibrary_WireAnimGraphOutputPose_Statics
struct UHT_STATICS
{
	struct AIStudioBridgeLibrary_eventWireAnimGraphOutputPose_Parms
	{
		UAnimBlueprint* AnimBlueprint;
		FName StateMachineName;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "CallInEditor", "true" },
		{ "Category", "Tech Connector|Animation" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Function WireAnimGraphOutputPose constinit property declarations ***************
	static const UECodeGen_Private::FObjectPropertyParams NewProp_AnimBlueprint;
	static const UECodeGen_Private::FNamePropertyParams NewProp_StateMachineName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function WireAnimGraphOutputPose constinit property declarations *****************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function WireAnimGraphOutputPose Property Definitions **************************
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_AnimBlueprint = { "AnimBlueprint", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventWireAnimGraphOutputPose_Parms, AnimBlueprint), Z_Construct_UClass_UAnimBlueprint, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_StateMachineName = { "StateMachineName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventWireAnimGraphOutputPose_Parms, StateMachineName), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(AIStudioBridgeLibrary_eventWireAnimGraphOutputPose_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_AnimBlueprint,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_StateMachineName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function WireAnimGraphOutputPose Property Definitions ****************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UAIStudioBridgeLibrary, nullptr, "WireAnimGraphOutputPose", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::AIStudioBridgeLibrary_eventWireAnimGraphOutputPose_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::AIStudioBridgeLibrary_eventWireAnimGraphOutputPose_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UAIStudioBridgeLibrary_WireAnimGraphOutputPose(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UAIStudioBridgeLibrary::execWireAnimGraphOutputPose)
{
	P_GET_OBJECT(UAnimBlueprint,Z_Param_AnimBlueprint);
	P_GET_PROPERTY(FNameProperty,Z_Param_StateMachineName);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UAIStudioBridgeLibrary::WireAnimGraphOutputPose(Z_Param_AnimBlueprint,Z_Param_StateMachineName);
	P_NATIVE_END;
}
// ********** End Class UAIStudioBridgeLibrary Function WireAnimGraphOutputPose ********************

// ********** Begin Class UAIStudioBridgeLibrary ***************************************************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UClass_UAIStudioBridgeLibrary_Statics
struct UHT_STATICS
{
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "IncludePath", "AIStudioBridgeLibrary.h" },
		{ "ModuleRelativePath", "Public/AIStudioBridgeLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Class UAIStudioBridgeLibrary constinit property declarations *******************
// ********** End Class UAIStudioBridgeLibrary constinit property declarations *********************
	static constexpr UE::CodeGen::FClassNativeFunction Funcs[] = {
		{ .NameUTF8 = UTF8TEXT("AddAnimGraphState"), .Pointer = &UAIStudioBridgeLibrary::execAddAnimGraphState },
		{ .NameUTF8 = UTF8TEXT("AddAnimGraphTransitionRule"), .Pointer = &UAIStudioBridgeLibrary::execAddAnimGraphTransitionRule },
		{ .NameUTF8 = UTF8TEXT("AddObjectReferenceToReflectedArray"), .Pointer = &UAIStudioBridgeLibrary::execAddObjectReferenceToReflectedArray },
		{ .NameUTF8 = UTF8TEXT("BindNiagaraUserParametersOnBeginPlay"), .Pointer = &UAIStudioBridgeLibrary::execBindNiagaraUserParametersOnBeginPlay },
		{ .NameUTF8 = UTF8TEXT("CompileAndSaveAnimBlueprint"), .Pointer = &UAIStudioBridgeLibrary::execCompileAndSaveAnimBlueprint },
		{ .NameUTF8 = UTF8TEXT("CreateKnownAssetByClassPath"), .Pointer = &UAIStudioBridgeLibrary::execCreateKnownAssetByClassPath },
		{ .NameUTF8 = UTF8TEXT("DeleteAnimGraphState"), .Pointer = &UAIStudioBridgeLibrary::execDeleteAnimGraphState },
		{ .NameUTF8 = UTF8TEXT("DeleteAnimGraphTransition"), .Pointer = &UAIStudioBridgeLibrary::execDeleteAnimGraphTransition },
		{ .NameUTF8 = UTF8TEXT("DescribeBlueprintNodeAction"), .Pointer = &UAIStudioBridgeLibrary::execDescribeBlueprintNodeAction },
		{ .NameUTF8 = UTF8TEXT("InjectKeyInPIE"), .Pointer = &UAIStudioBridgeLibrary::execInjectKeyInPIE },
		{ .NameUTF8 = UTF8TEXT("InspectAnimationSequence"), .Pointer = &UAIStudioBridgeLibrary::execInspectAnimationSequence },
		{ .NameUTF8 = UTF8TEXT("InspectAnimBlueprintGraph"), .Pointer = &UAIStudioBridgeLibrary::execInspectAnimBlueprintGraph },
		{ .NameUTF8 = UTF8TEXT("InspectCharacterInPIE"), .Pointer = &UAIStudioBridgeLibrary::execInspectCharacterInPIE },
		{ .NameUTF8 = UTF8TEXT("InspectReflectedAsset"), .Pointer = &UAIStudioBridgeLibrary::execInspectReflectedAsset },
		{ .NameUTF8 = UTF8TEXT("RemoveObjectReferenceFromReflectedArray"), .Pointer = &UAIStudioBridgeLibrary::execRemoveObjectReferenceFromReflectedArray },
		{ .NameUTF8 = UTF8TEXT("RenameAnimGraphState"), .Pointer = &UAIStudioBridgeLibrary::execRenameAnimGraphState },
		{ .NameUTF8 = UTF8TEXT("SearchBlueprintNodeActions"), .Pointer = &UAIStudioBridgeLibrary::execSearchBlueprintNodeActions },
		{ .NameUTF8 = UTF8TEXT("SetAnimGraphTransitionRule"), .Pointer = &UAIStudioBridgeLibrary::execSetAnimGraphTransitionRule },
		{ .NameUTF8 = UTF8TEXT("SetReflectedAssetProperty"), .Pointer = &UAIStudioBridgeLibrary::execSetReflectedAssetProperty },
		{ .NameUTF8 = UTF8TEXT("SynthesizeAnimGraphTransitionRuleExpression"), .Pointer = &UAIStudioBridgeLibrary::execSynthesizeAnimGraphTransitionRuleExpression },
		{ .NameUTF8 = UTF8TEXT("ValidateCharacterMontagesInPIE"), .Pointer = &UAIStudioBridgeLibrary::execValidateCharacterMontagesInPIE },
		{ .NameUTF8 = UTF8TEXT("WireAnimGraphOutputPose"), .Pointer = &UAIStudioBridgeLibrary::execWireAnimGraphOutputPose },
	};
	static FTypeConstructFunc* DependentSingletons[];
	static constexpr FClassFunctionLinkInfo FuncInfo[] = {
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_AddAnimGraphState, "AddAnimGraphState" }, // f35dfc6996c2c6e5db8ca0b2b77f19394f0f1506
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_AddAnimGraphTransitionRule, "AddAnimGraphTransitionRule" }, // 1b582ef88298443052dedcd99e300624571b4753
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_AddObjectReferenceToReflectedArray, "AddObjectReferenceToReflectedArray" }, // 4912535da509aadecb38e9c58e2d2a3685c3da94
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_BindNiagaraUserParametersOnBeginPlay, "BindNiagaraUserParametersOnBeginPlay" }, // 90628965f94bf3855c68d85635c2480aec5bf983
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_CompileAndSaveAnimBlueprint, "CompileAndSaveAnimBlueprint" }, // 5fa082f180bfebf932f77d006ea63c5cdd863d0d
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_CreateKnownAssetByClassPath, "CreateKnownAssetByClassPath" }, // 5db799a96596d48dcb880b4428332d33b53596b9
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_DeleteAnimGraphState, "DeleteAnimGraphState" }, // c7b63e27014684db3b50946cfda73d2b7832de38
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_DeleteAnimGraphTransition, "DeleteAnimGraphTransition" }, // 3ea809c6baf07c9435a2f44ec489f6c27dabddfa
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_DescribeBlueprintNodeAction, "DescribeBlueprintNodeAction" }, // 95c7c1da3e131581a50e8a96f0e4dbf3809de121
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InjectKeyInPIE, "InjectKeyInPIE" }, // ab3328a27e1172169b97ac35b797f5945a37a31e
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimationSequence, "InspectAnimationSequence" }, // 3ae259010ef345940e4a2069578e2da1888fef97
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimBlueprintGraph, "InspectAnimBlueprintGraph" }, // ee84cefb678a2fd7ab5377d82c43eca454440020
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectCharacterInPIE, "InspectCharacterInPIE" }, // b5c04f63dc9ab603cf3711d12d4c8942dcb75437
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectReflectedAsset, "InspectReflectedAsset" }, // e4dbd34c0df4a73401b609162ae65efbb66bf44c
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_RemoveObjectReferenceFromReflectedArray, "RemoveObjectReferenceFromReflectedArray" }, // 5d15ee2414fafe67d7109a159dd7de7134144918
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_RenameAnimGraphState, "RenameAnimGraphState" }, // b29dd99fd2aceddf6ddd755e6e03d93959156356
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_SearchBlueprintNodeActions, "SearchBlueprintNodeActions" }, // cd7bf63e2775499b4fc7fcb349635a7b895a4d16
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_SetAnimGraphTransitionRule, "SetAnimGraphTransitionRule" }, // 7ebc165db934cda8055c7c3b4219a8c1922eef56
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_SetReflectedAssetProperty, "SetReflectedAssetProperty" }, // 19bcef6aed27c5d271dc0e3842259f9f229d6a45
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_SynthesizeAnimGraphTransitionRuleExpression, "SynthesizeAnimGraphTransitionRuleExpression" }, // 7b753da7ab4ec99b1a0d1afcffa73beeb86f4c0a
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_ValidateCharacterMontagesInPIE, "ValidateCharacterMontagesInPIE" }, // 4301e9670987b795ef3ced925df4c0938d5b15c3
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_WireAnimGraphOutputPose, "WireAnimGraphOutputPose" }, // 9d2fec28aa7508a2af5bb384ccee54d78e59a89a
	};
	static_assert(UE_ARRAY_COUNT(FuncInfo) < 2048);
	static constexpr FCppClassTypeInfoStatic StaticCppClassTypeInfo = {
		TCppClassTypeTraits<UAIStudioBridgeLibrary>::IsAbstract,
	};
	static const UECodeGen_Private::FClassParams ClassParams;
}; // struct UHT_STATICS
FTypeConstructFunc* UHT_STATICS::DependentSingletons[] = {
	(FTypeConstructFunc*)Z_Construct_UClass_UBlueprintFunctionLibrary,
	(FTypeConstructFunc*)Z_Construct_UPackage__Script_AIStudioBridge,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::DependentSingletons) < 16);
const UECodeGen_Private::FClassParams UHT_STATICS::ClassParams = {
	&Z_Construct_UClass_UAIStudioBridgeLibrary,
	nullptr,
	&StaticCppClassTypeInfo,
	DependentSingletons,
	FuncInfo,
	nullptr,
	nullptr,
	UE_ARRAY_COUNT(DependentSingletons),
	UE_ARRAY_COUNT(FuncInfo),
	0,
	0,
	0x001000A0u,
	METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)
};
static void UAIStudioBridgeLibrary_StaticRegisterNativesUAIStudioBridgeLibrary()
{
	UClass* Class = UAIStudioBridgeLibrary::StaticClass();
	FNativeFunctionRegistrar::RegisterFunctions(Class, 		MakeConstArrayView(UHT_STATICS::Funcs));
}
FClassRegistrationInfo Z_Registration_Info_UClass_UAIStudioBridgeLibrary;
UClass* Z_Construct_UClass_UAIStudioBridgeLibrary(ETypeConstructPhase Phase)
{
	if (Phase == ETypeConstructPhase::Inner)
	{
		using TClass = UAIStudioBridgeLibrary;
		if (!Z_Registration_Info_UClass_UAIStudioBridgeLibrary.InnerSingleton)
		{
			GetPrivateStaticClassBody(
				TClass::StaticPackage(),
				TEXT("AIStudioBridgeLibrary"),
				Z_Registration_Info_UClass_UAIStudioBridgeLibrary.InnerSingleton,
				UAIStudioBridgeLibrary_StaticRegisterNativesUAIStudioBridgeLibrary,
				DataSizeOf<TClass>(),
				alignof(TClass),
				TClass::StaticClassFlags,
				TClass::StaticClassCastFlags(),
				TClass::StaticConfigName(),
				(UClass::ClassConstructorType)InternalConstructor<TClass>,
				(UClass::ClassVTableHelperCtorCallerType)InternalVTableHelperCtorCaller<TClass>,
				UOBJECT_CPPCLASS_STATICFUNCTIONS_FORCLASS(TClass),
				&TClass::Super::StaticClass,
				&TClass::WithinClass::StaticClass
			);
		}
		return Z_Registration_Info_UClass_UAIStudioBridgeLibrary.InnerSingleton;
	}
	if (!Z_Registration_Info_UClass_UAIStudioBridgeLibrary.OuterSingleton)
	{
		UECodeGen_Private::ConstructUClass(Z_Registration_Info_UClass_UAIStudioBridgeLibrary.OuterSingleton, UHT_STATICS::ClassParams);
	}
	return Z_Registration_Info_UClass_UAIStudioBridgeLibrary.OuterSingleton;
}
#undef UHT_STATICS
UAIStudioBridgeLibrary::UAIStudioBridgeLibrary(const FObjectInitializer& ObjectInitializer) : Super(ObjectInitializer) {}
DEFINE_VTABLE_PTR_HELPER_CTOR_NS(, UAIStudioBridgeLibrary);
UAIStudioBridgeLibrary::~UAIStudioBridgeLibrary() {}
// ********** End Class UAIStudioBridgeLibrary *****************************************************

// ********** Begin Registration *******************************************************************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_CompiledInDeferFile_FID_depot_tools_plugins_AIStudioBridge__build_AIStudioBridge_5_8_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h__Script_AIStudioBridge_Statics
struct UHT_STATICS
{
	static constexpr FClassRegisterCompiledInInfo ClassInfo[] = {
		{ Z_Construct_UClass_UAIStudioBridgeLibrary, TEXT("UAIStudioBridgeLibrary"), &Z_Registration_Info_UClass_UAIStudioBridgeLibrary, CONSTRUCT_RELOAD_VERSION_INFO(FClassReloadVersionInfo, sizeof(UAIStudioBridgeLibrary), 3511801049U) },
	};
}; // UHT_STATICS 
static FRegisterCompiledInInfo Z_CompiledInDeferFile_FID_depot_tools_plugins_AIStudioBridge__build_AIStudioBridge_5_8_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h__Script_AIStudioBridge_cb618765ea4e76b1cfa35245d25a8e0b40ce4ca0{
	TEXT("/Script/AIStudioBridge"),
	UHT_STATICS::ClassInfo, UE_ARRAY_COUNT(UHT_STATICS::ClassInfo),
	nullptr, 0,
	nullptr, 0,
	nullptr, 0,
};
#undef UHT_STATICS
// ********** End Registration *********************************************************************
#undef UHT_STRUCT_BASE

PRAGMA_ENABLE_DEPRECATION_WARNINGS
