#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "Animation/AnimBlueprint.h"
#include "Animation/BlendSpace.h"
#include "Animation/AnimMontage.h"
#include "Animation/AnimSequence.h"
#include "Engine/Blueprint.h"
#include "InputCoreTypes.h"
#include "AIStudioBridgeLibrary.generated.h"

UCLASS()
class AISTUDIOBRIDGE_API UAIStudioBridgeLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString InspectAnimBlueprintGraph(UAnimBlueprint* AnimBlueprint);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString AddAnimGraphStateMachine(UAnimBlueprint* AnimBlueprint, FName StateMachineName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString AddAnimGraphState(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName StateName, UObject* AnimationAsset);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString AddAnimGraphTransitionRule(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState, const FString& RuleExpression);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString DeleteAnimGraphState(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName StateName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString DeleteAnimGraphTransition(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString RenameAnimGraphState(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName OldStateName, FName NewStateName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString SetAnimGraphTransitionRule(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState, const FString& RuleExpression);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString SynthesizeAnimGraphTransitionRuleExpression(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState, const FString& RuleExpression);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString WireAnimGraphOutputPose(UAnimBlueprint* AnimBlueprint, FName StateMachineName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString CompileAndSaveAnimBlueprint(UAnimBlueprint* AnimBlueprint);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString InspectAnimationSequence(UAnimSequence* Animation);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString ConfigureBlendSpace(
        UBlendSpace* BlendSpace,
        const FString& SamplesJson,
        const FString& AxisXJson,
        const FString& AxisYJson,
        bool bSave = true);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Runtime")
    static FString InspectCharacterInPIE(UClass* CharacterClass, FString ExpectedAnimClassContains, const TArray<FName>& PropertyNames);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Runtime")
    static FString ValidateCharacterMontagesInPIE(UClass* CharacterClass, const TArray<UAnimMontage*>& Montages, FString ExpectedAnimClassContains);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Runtime")
    static FString InjectKeyInPIE(FKey Key, bool bPressed);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString DescribeBlueprintNodeAction(UBlueprint* Blueprint, FName GraphName, const FString& NodeWithCategory);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString SearchBlueprintNodeActions(UBlueprint* Blueprint, FName GraphName, const FString& Query, int32 MaxResults = 50);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString ConfigureBlueprintReplication(
        UBlueprint* Blueprint,
        const TArray<FName>& ReplicatedVariables,
        const TArray<FName>& RepNotifyVariables,
        const TArray<FName>& ServerRpcFunctions,
        bool bReliable = true,
        bool bSave = true);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString EnsureBlueprintFunction(
        UBlueprint* Blueprint,
        FName FunctionName,
        const FString& InputsJson,
        const FString& OutputsJson,
        bool bSave = true);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString RenameBlueprintSymbol(
        UBlueprint* Blueprint,
        FName OldName,
        FName NewName,
        bool bSave = true);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString BindNiagaraUserParametersOnBeginPlay(UBlueprint* Blueprint, const TArray<FName>& ComponentNames, const FString& BindingsJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString ListNiagaraModuleInputs(const FString& SystemPath, FName EmitterName = NAME_None);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString SetNiagaraUserParameter(const FString& SystemPath, FName ParameterName, const FString& ValueJson, const FString& ValueType = TEXT("float"));

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString SetNiagaraRendererProperty(const FString& SystemPath, FName EmitterName, int32 RendererIndex, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString SetNiagaraModuleInput(const FString& SystemPath, FName EmitterName, FName ScriptName, FName ModuleName, FName InputName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString RemoveNiagaraEmitter(const FString& SystemPath, FName EmitterName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString SetNiagaraEmitterProperty(const FString& SystemPath, FName EmitterName, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Motion Matching")
    static FString CreatePoseSearchSchema(const FString& SkeletonPath, const FString& AssetPath, int32 SampleRate = 30);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Motion Matching")
    static FString AddPoseSearchSchemaChannel(const FString& SchemaPath, const FString& ChannelClassPath, const FString& SettingsJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Motion Matching")
    static FString CreatePoseSearchDatabase(const FString& SchemaPath, const FString& AssetPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Motion Matching")
    static FString AddPoseSearchAnimation(const FString& DatabasePath, const FString& AnimationPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Motion Matching")
    static FString RemovePoseSearchAnimation(const FString& DatabasePath, const FString& AnimationPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString CreatePhysicsAsset(const FString& SkeletalMeshPath, const FString& AssetPath, bool bAssignToMesh = true);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString AddPhysicsBody(const FString& PhysicsAssetPath, FName BoneName, const FString& ShapeType = TEXT("capsule"));

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString AddPhysicsConstraint(const FString& PhysicsAssetPath, FName BoneNameA, FName BoneNameB);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString InspectPhysicsAsset(const FString& PhysicsAssetPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString SetPhysicsBodyProperty(const FString& PhysicsAssetPath, FName BodyName, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString SetPhysicsConstraintProperty(const FString& PhysicsAssetPath, FName ConstraintName, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString SetPhysicsProfileProperty(const FString& PhysicsAssetPath, FName ProfileName, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString ListPhysicsProfiles(const FString& PhysicsAssetPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString AddPhysicsProfile(const FString& PhysicsAssetPath, FName ProfileName, const FString& ProfileType, bool bAssignAll);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Physics")
    static FString RemovePhysicsProfile(const FString& PhysicsAssetPath, FName ProfileName, const FString& ProfileType);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString CreateKnownAssetByClassPath(const FString& AssetPath, const FString& ClassPath, const FString& InitialPropertiesJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString InspectReflectedAsset(const FString& AssetPath, const TArray<FName>& PropertyNames);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString SetReflectedAssetProperty(const FString& AssetPath, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString AddObjectReferenceToReflectedArray(const FString& AssetPath, FName PropertyName, const FString& ObjectPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString RemoveObjectReferenceFromReflectedArray(const FString& AssetPath, FName PropertyName, const FString& ObjectPath);
};
