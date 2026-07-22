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
		{ .NameUTF8 = UTF8TEXT("DescribeBlueprintNodeAction"), .Pointer = &UAIStudioBridgeLibrary::execDescribeBlueprintNodeAction },
		{ .NameUTF8 = UTF8TEXT("InjectKeyInPIE"), .Pointer = &UAIStudioBridgeLibrary::execInjectKeyInPIE },
		{ .NameUTF8 = UTF8TEXT("InspectAnimationSequence"), .Pointer = &UAIStudioBridgeLibrary::execInspectAnimationSequence },
		{ .NameUTF8 = UTF8TEXT("InspectAnimBlueprintGraph"), .Pointer = &UAIStudioBridgeLibrary::execInspectAnimBlueprintGraph },
		{ .NameUTF8 = UTF8TEXT("InspectCharacterInPIE"), .Pointer = &UAIStudioBridgeLibrary::execInspectCharacterInPIE },
		{ .NameUTF8 = UTF8TEXT("SearchBlueprintNodeActions"), .Pointer = &UAIStudioBridgeLibrary::execSearchBlueprintNodeActions },
		{ .NameUTF8 = UTF8TEXT("ValidateCharacterMontagesInPIE"), .Pointer = &UAIStudioBridgeLibrary::execValidateCharacterMontagesInPIE },
	};
	static FTypeConstructFunc* DependentSingletons[];
	static constexpr FClassFunctionLinkInfo FuncInfo[] = {
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_DescribeBlueprintNodeAction, "DescribeBlueprintNodeAction" }, // 95c7c1da3e131581a50e8a96f0e4dbf3809de121
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InjectKeyInPIE, "InjectKeyInPIE" }, // ab3328a27e1172169b97ac35b797f5945a37a31e
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimationSequence, "InspectAnimationSequence" }, // 3ae259010ef345940e4a2069578e2da1888fef97
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectAnimBlueprintGraph, "InspectAnimBlueprintGraph" }, // ee84cefb678a2fd7ab5377d82c43eca454440020
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_InspectCharacterInPIE, "InspectCharacterInPIE" }, // b5c04f63dc9ab603cf3711d12d4c8942dcb75437
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_SearchBlueprintNodeActions, "SearchBlueprintNodeActions" }, // cd7bf63e2775499b4fc7fcb349635a7b895a4d16
		{ &Z_Construct_UFunction_UAIStudioBridgeLibrary_ValidateCharacterMontagesInPIE, "ValidateCharacterMontagesInPIE" }, // 4301e9670987b795ef3ced925df4c0938d5b15c3
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
#define UHT_STATICS Z_CompiledInDeferFile_FID_depot_tools_plugins_AIStudioBridge__build_search_actions_package_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h__Script_AIStudioBridge_Statics
struct UHT_STATICS
{
	static constexpr FClassRegisterCompiledInInfo ClassInfo[] = {
		{ Z_Construct_UClass_UAIStudioBridgeLibrary, TEXT("UAIStudioBridgeLibrary"), &Z_Registration_Info_UClass_UAIStudioBridgeLibrary, CONSTRUCT_RELOAD_VERSION_INFO(FClassReloadVersionInfo, sizeof(UAIStudioBridgeLibrary), 1677766427U) },
	};
}; // UHT_STATICS 
static FRegisterCompiledInInfo Z_CompiledInDeferFile_FID_depot_tools_plugins_AIStudioBridge__build_search_actions_package_HostProject_Plugins_AIStudioBridge_Source_AIStudioBridge_Public_AIStudioBridgeLibrary_h__Script_AIStudioBridge_f0d95d31467f630364ef262d9ef3cee790fe75c3{
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
