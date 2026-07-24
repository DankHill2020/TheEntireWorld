#include "AIStudioBridgeLibrary.h"

#if WITH_EDITOR
#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraphSchema_K2.h"
#include "BlueprintActionDatabase.h"
#include "BlueprintActionFilter.h"
#include "BlueprintNodeSpawner.h"
#include "AnimGraphNode_Root.h"
#include "AnimGraphNode_SequencePlayer.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimGraphNode_StateMachineBase.h"
#include "AnimGraphNode_TransitionResult.h"
#include "AnimStateNode.h"
#include "AnimStateNodeBase.h"
#include "AnimStateTransitionNode.h"
#include "Animation/AnimationAsset.h"
#include "Animation/BlendSpace.h"
#include "AnimationGraph.h"
#include "AnimationGraphSchema.h"
#include "AnimationStateGraph.h"
#include "AnimationStateMachineGraph.h"
#include "AnimationStateMachineSchema.h"
#include "AnimationTransitionGraph.h"
#include "EdGraphUtilities.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "K2Node_CallFunction.h"
#include "K2Node_Event.h"
#include "K2Node_ExecutionSequence.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_FunctionResult.h"
#include "K2Node_EditablePinBase.h"
#include "K2Node_VariableGet.h"
#include "Kismet/KismetMathLibrary.h"
#include "Components/ActorComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "InputKeyEventArgs.h"
#include "NiagaraComponent.h"
#include "NiagaraExternalSystemEditorUtilities.h"
#include "NiagaraSystem.h"
#include "NiagaraTypes.h"
#include "Animation/Skeleton.h"
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/BodySetup.h"
#include "PhysicsEngine/BodyInstance.h"
#include "PhysicsEngine/PhysicsConstraintTemplate.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "Factories/PhysicsAssetFactory.h"
#include "PhysicsAssetUtils.h"
#include "PoseSearch/PoseSearchDatabase.h"
#include "PoseSearch/PoseSearchFeatureChannel.h"
#include "PoseSearch/PoseSearchSchema.h"
#include "UObject/UnrealType.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "JsonObjectConverter.h"
#include "Misc/PackageName.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "ScopedTransaction.h"
#include "UObject/SavePackage.h"
#endif

static FString AIStudioJsonString(const TSharedRef<FJsonObject>& Object)
{
    FString Output;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Object, Writer);
    return Output;
}

#if WITH_EDITOR
static void AIStudioCollectBlueprintGraphs(UBlueprint* Blueprint, TArray<UEdGraph*>& Graphs)
{
    if (!Blueprint)
    {
        return;
    }
    Graphs.Append(Blueprint->UbergraphPages);
    Graphs.Append(Blueprint->FunctionGraphs);
    Graphs.Append(Blueprint->MacroGraphs);
    Graphs.Append(Blueprint->DelegateSignatureGraphs);
}

static UAnimationStateMachineGraph* AIStudioFindStateMachineGraph(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    UAnimGraphNode_StateMachineBase** OutOwnerNode = nullptr)
{
    if (OutOwnerNode)
    {
        *OutOwnerNode = nullptr;
    }
    if (!AnimBlueprint)
    {
        return nullptr;
    }

    TArray<UAnimGraphNode_StateMachineBase*> StateMachineNodes;
    FBlueprintEditorUtils::GetAllNodesOfClassEx<UAnimGraphNode_StateMachineBase>(
        AnimBlueprint,
        StateMachineNodes);
    for (UAnimGraphNode_StateMachineBase* Node : StateMachineNodes)
    {
        if (!Node || !Node->EditorStateMachineGraph)
        {
            continue;
        }
        const FString Requested = StateMachineName.ToString();
        if (StateMachineName.IsNone()
            || Node->EditorStateMachineGraph->GetFName() == StateMachineName
            || Node->GetStateMachineName().Equals(Requested, ESearchCase::IgnoreCase))
        {
            if (OutOwnerNode)
            {
                *OutOwnerNode = Node;
            }
            return Node->EditorStateMachineGraph;
        }
    }
    return nullptr;
}

static UAnimStateNode* AIStudioFindStateNode(UAnimationStateMachineGraph* Graph, FName StateName)
{
    if (!Graph)
    {
        return nullptr;
    }
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        UAnimStateNode* StateNode = Cast<UAnimStateNode>(Node);
        if (StateNode && StateNode->GetStateName().Equals(StateName.ToString(), ESearchCase::IgnoreCase))
        {
            return StateNode;
        }
    }
    return nullptr;
}

static UAnimStateTransitionNode* AIStudioFindTransitionNode(
    UAnimationStateMachineGraph* Graph,
    UAnimStateNodeBase* FromState,
    UAnimStateNodeBase* ToState)
{
    if (!Graph || !FromState || !ToState)
    {
        return nullptr;
    }
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        UAnimStateTransitionNode* Transition = Cast<UAnimStateTransitionNode>(Node);
        if (Transition && Transition->GetPreviousState() == FromState && Transition->GetNextState() == ToState)
        {
            return Transition;
        }
    }
    return nullptr;
}

static UEdGraphPin* AIStudioFindPosePin(UEdGraphNode* Node, EEdGraphPinDirection Direction)
{
    if (!Node)
    {
        return nullptr;
    }
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (Pin && Pin->Direction == Direction && UAnimationGraphSchema::IsPosePin(Pin->PinType))
        {
            return Pin;
        }
    }
    return nullptr;
}

static UAnimationGraph* AIStudioFindAnimationGraphForNode(UEdGraphNode* Node)
{
    return Node ? Cast<UAnimationGraph>(Node->GetGraph()) : nullptr;
}

static TSharedPtr<FJsonObject> AIStudioParseJsonObject(const FString& JsonText)
{
    if (JsonText.TrimStartAndEnd().IsEmpty())
    {
        return MakeShared<FJsonObject>();
    }
    TSharedPtr<FJsonObject> Parsed;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
    if (FJsonSerializer::Deserialize(Reader, Parsed) && Parsed.IsValid())
    {
        return Parsed;
    }
    return nullptr;
}

static TSharedPtr<FJsonValue> AIStudioParseJsonValueOrString(const FString& JsonText)
{
    TSharedPtr<FJsonValue> Parsed;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
    if (FJsonSerializer::Deserialize(Reader, Parsed) && Parsed.IsValid())
    {
        return Parsed;
    }
    return MakeShared<FJsonValueString>(JsonText);
}

static void AIStudioSetJsonValueField(const TSharedRef<FJsonObject>& Object, const FString& FieldName, const FJsonValue* Value)
{
    if (!Value)
    {
        Object->SetStringField(FieldName, TEXT(""));
        return;
    }
    switch (Value->Type)
    {
    case EJson::Boolean:
        Object->SetBoolField(FieldName, Value->AsBool());
        break;
    case EJson::Number:
        Object->SetNumberField(FieldName, Value->AsNumber());
        break;
    case EJson::String:
        Object->SetStringField(FieldName, Value->AsString());
        break;
    default:
        Object->SetStringField(FieldName, TEXT("<complex>"));
        break;
    }
}

static FString AIStudioPackageNameFromAssetPath(const FString& AssetPath)
{
    FString PackageName;
    FString AssetName;
    AssetPath.Split(TEXT("."), &PackageName, &AssetName);
    return PackageName.IsEmpty() ? AssetPath : PackageName;
}

static FString AIStudioAssetNameFromAssetPath(const FString& AssetPath)
{
    FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    FString AssetName;
    if (PackageName.Split(TEXT("/"), nullptr, &AssetName, ESearchCase::CaseSensitive, ESearchDir::FromEnd))
    {
        return AssetName;
    }
    return PackageName;
}

static UObject* AIStudioLoadAssetObject(const FString& AssetPath)
{
    return StaticLoadObject(UObject::StaticClass(), nullptr, *AssetPath);
}

static bool AIStudioSaveAssetPackage(UObject* Asset)
{
    if (!Asset)
    {
        return false;
    }
    UPackage* Package = Asset->GetOutermost();
    if (!Package)
    {
        return false;
    }
    Package->MarkPackageDirty();
    const FString PackageName = Package->GetName();
    FString FileName;
    if (!FPackageName::TryConvertLongPackageNameToFilename(
        PackageName,
        FileName,
        FPackageName::GetAssetPackageExtension()))
    {
        return false;
    }
    FSavePackageArgs SaveArgs;
    SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
    SaveArgs.SaveFlags = SAVE_None;
    return UPackage::SavePackage(Package, Asset, *FileName, SaveArgs);
}

static bool AIStudioApplyBlendParameterJson(
    const FString& JsonText,
    FBlendParameter& Parameter,
    FString& OutError)
{
    const TSharedPtr<FJsonObject> Parsed = AIStudioParseJsonObject(JsonText);
    if (!Parsed.IsValid())
    {
        OutError = TEXT("Axis settings are not valid JSON.");
        return false;
    }
    FString DisplayName;
    if (Parsed->TryGetStringField(TEXT("name"), DisplayName))
    {
        Parameter.DisplayName = DisplayName;
    }
    double Number = 0.0;
    if (Parsed->TryGetNumberField(TEXT("min"), Number))
    {
        Parameter.Min = static_cast<float>(Number);
    }
    if (Parsed->TryGetNumberField(TEXT("max"), Number))
    {
        Parameter.Max = static_cast<float>(Number);
    }
    if (Parsed->TryGetNumberField(TEXT("grid_num"), Number))
    {
        Parameter.GridNum = FMath::Max(1, static_cast<int32>(Number));
    }
    bool Flag = false;
    if (Parsed->TryGetBoolField(TEXT("snap_to_grid"), Flag))
    {
        Parameter.bSnapToGrid = Flag;
    }
    if (Parsed->TryGetBoolField(TEXT("wrap_input"), Flag))
    {
        Parameter.bWrapInput = Flag;
    }
    if (Parameter.Max <= Parameter.Min)
    {
        OutError = TEXT("Axis maximum must be greater than its minimum.");
        return false;
    }
    return true;
}

static TSharedRef<FJsonObject> AIStudioReflectedPropertyValue(UObject* Object, FProperty* Property)
{
    const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("name"), Property ? Property->GetName() : TEXT(""));
    Row->SetStringField(TEXT("type"), Property ? Property->GetCPPType() : TEXT(""));
    if (!Object || !Property)
    {
        Row->SetStringField(TEXT("value"), TEXT(""));
        return Row;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    FString Exported;
    Property->ExportTextItem_Direct(Exported, ValuePtr, nullptr, Object, PPF_None);
    Row->SetStringField(TEXT("value"), Exported);
    return Row;
}

static TSharedRef<FJsonObject> AIStudioContainerPropertyValue(
    void* Container,
    UObject* Owner,
    FProperty* Property)
{
    const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("name"), Property ? Property->GetName() : TEXT(""));
    Row->SetStringField(TEXT("type"), Property ? Property->GetCPPType() : TEXT(""));
    if (!Container || !Property)
    {
        Row->SetStringField(TEXT("value"), TEXT(""));
        return Row;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Container);
    FString Exported;
    Property->ExportTextItem_Direct(Exported, ValuePtr, nullptr, Owner, PPF_None);
    Row->SetStringField(TEXT("value"), Exported);
    return Row;
}

static FProperty* AIStudioFindFlexibleProperty(UStruct* Struct, FName RequestedName)
{
    if (!Struct)
    {
        return nullptr;
    }
    if (FProperty* Exact = Struct->FindPropertyByName(RequestedName))
    {
        return Exact;
    }
    FString NormalizedRequest = RequestedName.ToString().ToLower();
    NormalizedRequest.ReplaceInline(TEXT("_"), TEXT(""));
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        FString Candidate = It->GetName().ToLower();
        Candidate.ReplaceInline(TEXT("_"), TEXT(""));
        if (Candidate == NormalizedRequest)
        {
            return *It;
        }
        if (Candidate.Len() > 1 && Candidate[0] == TCHAR('b') && Candidate.Mid(1) == NormalizedRequest)
        {
            return *It;
        }
    }
    return nullptr;
}

static bool AIStudioSetPropertyOnContainerFromJsonValue(
    void* Container,
    UObject* Owner,
    FProperty* Property,
    const FJsonValue* Value,
    FString& OutError)
{
    if (!Container || !Property || !Value)
    {
        OutError = TEXT("Container, property, and JSON value are required.");
        return false;
    }
    void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Container);
    if (FBoolProperty* BoolProperty = CastField<FBoolProperty>(Property))
    {
        BoolProperty->SetPropertyValue(ValuePtr, Value->AsBool());
        return true;
    }
    if (FNumericProperty* NumericProperty = CastField<FNumericProperty>(Property))
    {
        if (NumericProperty->IsInteger())
        {
            NumericProperty->SetIntPropertyValue(ValuePtr, static_cast<int64>(Value->AsNumber()));
        }
        else
        {
            NumericProperty->SetFloatingPointPropertyValue(ValuePtr, Value->AsNumber());
        }
        return true;
    }
    if (FStrProperty* StrProperty = CastField<FStrProperty>(Property))
    {
        StrProperty->SetPropertyValue(ValuePtr, Value->AsString());
        return true;
    }
    if (FNameProperty* NameProperty = CastField<FNameProperty>(Property))
    {
        NameProperty->SetPropertyValue(ValuePtr, FName(*Value->AsString()));
        return true;
    }
    if (FTextProperty* TextProperty = CastField<FTextProperty>(Property))
    {
        TextProperty->SetPropertyValue(ValuePtr, FText::FromString(Value->AsString()));
        return true;
    }
    if (FObjectProperty* ObjectProperty = CastField<FObjectProperty>(Property))
    {
        UObject* LoadedObject = AIStudioLoadAssetObject(Value->AsString());
        if (!LoadedObject)
        {
            OutError = FString::Printf(TEXT("Could not load object value '%s'."), *Value->AsString());
            return false;
        }
        if (!LoadedObject->IsA(ObjectProperty->PropertyClass))
        {
            OutError = FString::Printf(TEXT("Loaded object '%s' is not a %s."), *Value->AsString(), *ObjectProperty->PropertyClass->GetName());
            return false;
        }
        ObjectProperty->SetObjectPropertyValue(ValuePtr, LoadedObject);
        return true;
    }
    FString Imported = Value->Type == EJson::String ? Value->AsString() : TEXT("");
    if (!Imported.IsEmpty() && Property->ImportText_Direct(*Imported, ValuePtr, Owner, PPF_None))
    {
        return true;
    }
    OutError = FString::Printf(TEXT("Unsupported reflected property type '%s'."), *Property->GetCPPType());
    return false;
}

static bool AIStudioSetPropertyFromJsonValue(UObject* Object, FProperty* Property, const FJsonValue* Value, FString& OutError)
{
    return AIStudioSetPropertyOnContainerFromJsonValue(Object, Object, Property, Value, OutError);
}

static bool AIStudioSetPropertiesFromJson(UObject* Object, const TSharedPtr<FJsonObject>& Properties, TArray<FString>& OutErrors)
{
    if (!Object || !Properties.IsValid())
    {
        return false;
    }
    bool bAnyApplied = false;
    for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Properties->Values)
    {
        FProperty* Property = Object->GetClass()->FindPropertyByName(FName(*Pair.Key));
        if (!Property)
        {
            OutErrors.Add(FString::Printf(TEXT("Property '%s' was not found on %s."), *Pair.Key, *Object->GetClass()->GetName()));
            continue;
        }
        FString Error;
        if (AIStudioSetPropertyFromJsonValue(Object, Property, Pair.Value.Get(), Error))
        {
            bAnyApplied = true;
        }
        else
        {
            OutErrors.Add(Error);
        }
    }
    return bAnyApplied || Properties->Values.Num() == 0;
}

static UK2Node_CallFunction* AIStudioCreateMathCallNode(
    UEdGraph* Graph,
    FName FunctionName,
    int32 NodePosX,
    int32 NodePosY)
{
    if (!Graph)
    {
        return nullptr;
    }
    const UFunction* Function = UKismetMathLibrary::StaticClass()->FindFunctionByName(FunctionName);
    if (!Function)
    {
        return nullptr;
    }

    UK2Node_CallFunction* CallNode = NewObject<UK2Node_CallFunction>(Graph);
    Graph->Modify();
    Graph->AddNode(CallNode, true, false);
    CallNode->CreateNewGuid();
    CallNode->PostPlacedNewNode();
    CallNode->SetFromFunction(Function);
    CallNode->NodePosX = NodePosX;
    CallNode->NodePosY = NodePosY;
    CallNode->AllocateDefaultPins();
    return CallNode;
}

static UK2Node_VariableGet* AIStudioCreateVariableGetNode(
    UEdGraph* Graph,
    FName VariableName,
    int32 NodePosX,
    int32 NodePosY)
{
    if (!Graph || VariableName.IsNone())
    {
        return nullptr;
    }

    UK2Node_VariableGet* VariableNode = NewObject<UK2Node_VariableGet>(Graph);
    Graph->Modify();
    Graph->AddNode(VariableNode, true, false);
    VariableNode->CreateNewGuid();
    VariableNode->PostPlacedNewNode();
    VariableNode->VariableReference.SetSelfMember(VariableName);
    VariableNode->NodePosX = NodePosX;
    VariableNode->NodePosY = NodePosY;
    VariableNode->AllocateDefaultPins();
    return VariableNode;
}

static UEdGraphPin* AIStudioFindFirstOutputPin(UEdGraphNode* Node)
{
    if (!Node)
    {
        return nullptr;
    }
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (Pin && Pin->Direction == EGPD_Output)
        {
            return Pin;
        }
    }
    return nullptr;
}

static UEdGraphPin* AIStudioFindReturnPin(UEdGraphNode* Node)
{
    return Node ? Node->FindPin(TEXT("ReturnValue")) : nullptr;
}

static bool AIStudioConnectPins(UEdGraph* Graph, UEdGraphPin* OutputPin, UEdGraphPin* InputPin)
{
    if (!Graph || !OutputPin || !InputPin)
    {
        return false;
    }
    const UEdGraphSchema* Schema = Graph->GetSchema();
    return Schema && Schema->TryCreateConnection(OutputPin, InputPin);
}

static bool AIStudioParseDouble(const FString& Text, double& OutValue)
{
    const FString Trimmed = Text.TrimStartAndEnd();
    if (Trimmed.IsEmpty())
    {
        return false;
    }
    return LexTryParseString(OutValue, *Trimmed);
}

static FName AIStudioComparisonFunctionForOperator(const FString& Operator)
{
    if (Operator == TEXT(">"))
    {
        return GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, Greater_DoubleDouble);
    }
    if (Operator == TEXT("<"))
    {
        return GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, Less_DoubleDouble);
    }
    if (Operator == TEXT(">="))
    {
        return GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, GreaterEqual_DoubleDouble);
    }
    if (Operator == TEXT("<="))
    {
        return GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, LessEqual_DoubleDouble);
    }
    if (Operator == TEXT("=="))
    {
        return GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, EqualEqual_DoubleDouble);
    }
    if (Operator == TEXT("!="))
    {
        return GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, NotEqual_DoubleDouble);
    }
    return NAME_None;
}

static bool AIStudioSplitComparison(
    const FString& Atom,
    FString& OutLeft,
    FString& OutOperator,
    FString& OutRight)
{
    static const TArray<FString> Operators = {
        TEXT(">="),
        TEXT("<="),
        TEXT("=="),
        TEXT("!="),
        TEXT(">"),
        TEXT("<"),
    };
    for (const FString& Operator : Operators)
    {
        int32 Index = INDEX_NONE;
        if (Atom.FindChar(Operator[0], Index))
        {
            Index = Atom.Find(Operator, ESearchCase::CaseSensitive);
            if (Index != INDEX_NONE)
            {
                OutLeft = Atom.Left(Index).TrimStartAndEnd();
                OutOperator = Operator;
                OutRight = Atom.Mid(Index + Operator.Len()).TrimStartAndEnd();
                return !OutLeft.IsEmpty() && !OutRight.IsEmpty();
            }
        }
    }
    return false;
}

static UEdGraphPin* AIStudioBuildNumericReadPin(
    UEdGraph* Graph,
    const FString& VariableExpression,
    int32 NodePosX,
    int32 NodePosY,
    TArray<FString>& OutUnsupportedReasons)
{
    FString VariableName = VariableExpression.TrimStartAndEnd();
    FString ComponentName;
    int32 DotIndex = INDEX_NONE;
    if (VariableName.FindChar(TEXT('.'), DotIndex))
    {
        ComponentName = VariableName.Mid(DotIndex + 1).TrimStartAndEnd().ToUpper();
        VariableName = VariableName.Left(DotIndex).TrimStartAndEnd();
    }

    UK2Node_VariableGet* VariableNode = AIStudioCreateVariableGetNode(Graph, FName(*VariableName), NodePosX, NodePosY);
    UEdGraphPin* VariablePin = AIStudioFindFirstOutputPin(VariableNode);
    if (!VariablePin)
    {
        OutUnsupportedReasons.Add(FString::Printf(TEXT("Could not create/read variable '%s'."), *VariableName));
        return nullptr;
    }
    if (ComponentName.IsEmpty())
    {
        return VariablePin;
    }
    if (ComponentName != TEXT("X") && ComponentName != TEXT("Y") && ComponentName != TEXT("Z"))
    {
        OutUnsupportedReasons.Add(FString::Printf(TEXT("Unsupported vector component '%s'."), *ComponentName));
        return nullptr;
    }

    UK2Node_CallFunction* BreakNode = AIStudioCreateMathCallNode(
        Graph,
        GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, BreakVector),
        NodePosX + 220,
        NodePosY);
    if (!BreakNode)
    {
        OutUnsupportedReasons.Add(TEXT("Could not create BreakVector node."));
        return nullptr;
    }
    if (!AIStudioConnectPins(Graph, VariablePin, BreakNode->FindPin(TEXT("InVec"))))
    {
        OutUnsupportedReasons.Add(FString::Printf(TEXT("Could not connect '%s' to BreakVector."), *VariableName));
        return nullptr;
    }
    return BreakNode->FindPin(*ComponentName);
}

static UEdGraphPin* AIStudioBuildRuleAtomPin(
    UEdGraph* Graph,
    const FString& AtomExpression,
    int32 NodePosX,
    int32 NodePosY,
    TArray<FString>& OutUnsupportedReasons)
{
    FString Atom = AtomExpression.TrimStartAndEnd();
    if (Atom.StartsWith(TEXT("(")) && Atom.EndsWith(TEXT(")")))
    {
        Atom = Atom.Mid(1, Atom.Len() - 2).TrimStartAndEnd();
    }
    bool bNegate = false;
    while (Atom.StartsWith(TEXT("!")))
    {
        bNegate = !bNegate;
        Atom = Atom.Mid(1).TrimStartAndEnd();
    }

    UEdGraphPin* ConditionPin = nullptr;
    FString Left;
    FString Operator;
    FString Right;
    if (AIStudioSplitComparison(Atom, Left, Operator, Right))
    {
        double LiteralValue = 0.0;
        if (!AIStudioParseDouble(Right, LiteralValue))
        {
            OutUnsupportedReasons.Add(FString::Printf(TEXT("Comparison right side must be a numeric literal: '%s'."), *Atom));
            return nullptr;
        }
        UEdGraphPin* LeftPin = AIStudioBuildNumericReadPin(Graph, Left, NodePosX, NodePosY, OutUnsupportedReasons);
        UK2Node_CallFunction* CompareNode = AIStudioCreateMathCallNode(
            Graph,
            AIStudioComparisonFunctionForOperator(Operator),
            NodePosX + 460,
            NodePosY);
        if (!LeftPin || !CompareNode)
        {
            OutUnsupportedReasons.Add(FString::Printf(TEXT("Could not synthesize comparison '%s'."), *Atom));
            return nullptr;
        }
        AIStudioConnectPins(Graph, LeftPin, CompareNode->FindPin(TEXT("A")));
        if (UEdGraphPin* BPin = CompareNode->FindPin(TEXT("B")))
        {
            BPin->DefaultValue = FString::SanitizeFloat(LiteralValue);
        }
        ConditionPin = AIStudioFindReturnPin(CompareNode);
    }
    else
    {
        UK2Node_VariableGet* VariableNode = AIStudioCreateVariableGetNode(Graph, FName(*Atom), NodePosX, NodePosY);
        ConditionPin = AIStudioFindFirstOutputPin(VariableNode);
        if (!ConditionPin)
        {
            OutUnsupportedReasons.Add(FString::Printf(TEXT("Could not create/read boolean variable '%s'."), *Atom));
            return nullptr;
        }
    }

    if (bNegate)
    {
        UK2Node_CallFunction* NotNode = AIStudioCreateMathCallNode(
            Graph,
            GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, Not_PreBool),
            NodePosX + 700,
            NodePosY);
        if (!NotNode || !AIStudioConnectPins(Graph, ConditionPin, NotNode->FindPin(TEXT("A"))))
        {
            OutUnsupportedReasons.Add(FString::Printf(TEXT("Could not synthesize negation for '%s'."), *AtomExpression));
            return nullptr;
        }
        ConditionPin = AIStudioFindReturnPin(NotNode);
    }
    return ConditionPin;
}

static bool AIStudioApplyConstantTransitionRule(
    UAnimGraphNode_TransitionResult* ResultNode,
    const FString& NormalizedRule,
    bool& OutRuleValue)
{
    if (!ResultNode)
    {
        return false;
    }
    const bool bSupportedConstantRule = NormalizedRule.IsEmpty()
        || NormalizedRule == TEXT("true")
        || NormalizedRule == TEXT("false")
        || NormalizedRule == TEXT("always")
        || NormalizedRule == TEXT("never");
    if (!bSupportedConstantRule)
    {
        return false;
    }
    OutRuleValue = !(NormalizedRule == TEXT("false") || NormalizedRule == TEXT("never"));
    if (UEdGraphPin* CanEnterPin = ResultNode->FindPin(TEXT("bCanEnterTransition")))
    {
        CanEnterPin->Modify();
        CanEnterPin->BreakAllPinLinks();
        CanEnterPin->DefaultValue = OutRuleValue ? TEXT("true") : TEXT("false");
        return true;
    }
    return false;
}

static bool AIStudioSynthesizeTransitionRuleGraph(
    UAnimationTransitionGraph* TransitionGraph,
    const FString& RuleExpression,
    TArray<FString>& OutUnsupportedReasons,
    int32& OutCreatedNodeCount,
    FString& OutFinalSourceNode)
{
    OutCreatedNodeCount = 0;
    if (!TransitionGraph)
    {
        OutUnsupportedReasons.Add(TEXT("Transition graph was null."));
        return false;
    }
    UAnimGraphNode_TransitionResult* ResultNode = TransitionGraph->GetResultNode();
    UEdGraphPin* CanEnterPin = ResultNode ? ResultNode->FindPin(TEXT("bCanEnterTransition")) : nullptr;
    if (!CanEnterPin)
    {
        OutUnsupportedReasons.Add(TEXT("Transition result node did not expose bCanEnterTransition."));
        return false;
    }

    const int32 BeforeNodes = TransitionGraph->Nodes.Num();
    TArray<FString> Terms;
    RuleExpression.ParseIntoArray(Terms, TEXT("&&"), true);
    if (Terms.IsEmpty())
    {
        OutUnsupportedReasons.Add(TEXT("Rule expression was empty."));
        return false;
    }
    if (RuleExpression.Contains(TEXT("||")))
    {
        OutUnsupportedReasons.Add(TEXT("OR expressions are not yet supported; use && terms or split the transition."));
        return false;
    }

    TArray<UEdGraphPin*> TermPins;
    for (int32 Index = 0; Index < Terms.Num(); ++Index)
    {
        UEdGraphPin* TermPin = AIStudioBuildRuleAtomPin(
            TransitionGraph,
            Terms[Index],
            ResultNode->NodePosX - 920,
            ResultNode->NodePosY + Index * 150,
            OutUnsupportedReasons);
        if (!TermPin)
        {
            return false;
        }
        TermPins.Add(TermPin);
    }

    UEdGraphPin* FinalPin = TermPins[0];
    for (int32 Index = 1; Index < TermPins.Num(); ++Index)
    {
        UK2Node_CallFunction* AndNode = AIStudioCreateMathCallNode(
            TransitionGraph,
            GET_FUNCTION_NAME_CHECKED(UKismetMathLibrary, BooleanAND),
            ResultNode->NodePosX - 300,
            ResultNode->NodePosY + Index * 120);
        if (!AndNode
            || !AIStudioConnectPins(TransitionGraph, FinalPin, AndNode->FindPin(TEXT("A")))
            || !AIStudioConnectPins(TransitionGraph, TermPins[Index], AndNode->FindPin(TEXT("B"))))
        {
            OutUnsupportedReasons.Add(TEXT("Could not synthesize BooleanAND chain."));
            return false;
        }
        FinalPin = AIStudioFindReturnPin(AndNode);
    }

    CanEnterPin->Modify();
    CanEnterPin->BreakAllPinLinks();
    CanEnterPin->DefaultValue.Reset();
    if (!AIStudioConnectPins(TransitionGraph, FinalPin, CanEnterPin))
    {
        OutUnsupportedReasons.Add(TEXT("Could not connect synthesized rule result into bCanEnterTransition."));
        return false;
    }
    OutCreatedNodeCount = TransitionGraph->Nodes.Num() - BeforeNodes;
    OutFinalSourceNode = FinalPin && FinalPin->GetOwningNode() ? FinalPin->GetOwningNode()->GetNodeTitle(ENodeTitleType::ListView).ToString() : TEXT("");
    return true;
}
#endif

FString UAIStudioBridgeLibrary::InspectAnimBlueprintGraph(UAnimBlueprint* AnimBlueprint)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_anim_blueprint_graph"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }

    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());

    TArray<UEdGraph*> Graphs;
    AIStudioCollectBlueprintGraphs(AnimBlueprint, Graphs);

    TArray<TSharedPtr<FJsonValue>> GraphValues;
    for (UEdGraph* Graph : Graphs)
    {
        if (!Graph)
        {
            continue;
        }

        const TSharedRef<FJsonObject> GraphObject = MakeShared<FJsonObject>();
        GraphObject->SetStringField(TEXT("name"), Graph->GetName());
        GraphObject->SetStringField(TEXT("class"), Graph->GetClass()->GetName());

        TArray<TSharedPtr<FJsonValue>> NodeValues;
        for (UEdGraphNode* Node : Graph->Nodes)
        {
            if (!Node)
            {
                continue;
            }

            const TSharedRef<FJsonObject> NodeObject = MakeShared<FJsonObject>();
            NodeObject->SetStringField(TEXT("name"), Node->GetName());
            NodeObject->SetStringField(TEXT("title"), Node->GetNodeTitle(ENodeTitleType::ListView).ToString());
            NodeObject->SetStringField(TEXT("class"), Node->GetClass()->GetName());
            NodeObject->SetNumberField(TEXT("pin_count"), Node->Pins.Num());

            TArray<TSharedPtr<FJsonValue>> PinValues;
            for (UEdGraphPin* Pin : Node->Pins)
            {
                if (!Pin)
                {
                    continue;
                }
                const TSharedRef<FJsonObject> PinObject = MakeShared<FJsonObject>();
                PinObject->SetStringField(TEXT("name"), Pin->PinName.ToString());
                PinObject->SetStringField(TEXT("direction"), Pin->Direction == EGPD_Input ? TEXT("input") : TEXT("output"));
                PinObject->SetStringField(TEXT("category"), Pin->PinType.PinCategory.ToString());
                PinObject->SetNumberField(TEXT("linked_to_count"), Pin->LinkedTo.Num());
                PinValues.Add(MakeShared<FJsonValueObject>(PinObject));
            }
            NodeObject->SetArrayField(TEXT("pins"), PinValues);
            NodeValues.Add(MakeShared<FJsonValueObject>(NodeObject));
        }

        GraphObject->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());
        GraphObject->SetArrayField(TEXT("nodes"), NodeValues);
        GraphValues.Add(MakeShared<FJsonValueObject>(GraphObject));
    }

    Root->SetArrayField(TEXT("graphs"), GraphValues);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph(anim_bp)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif

    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CreateKnownAssetByClassPath(
    const FString& AssetPath,
    const FString& ClassPath,
    const FString& InitialPropertiesJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_known_asset_by_class_path"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("asset_path"), AssetPath);
    Root->SetStringField(TEXT("class_path"), ClassPath);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_known_asset_by_class_path(asset_path, class_path, initial_properties_json)"));

#if WITH_EDITOR
    UClass* AssetClass = LoadClass<UObject>(nullptr, *ClassPath);
    TSharedPtr<FJsonObject> InitialProperties = AIStudioParseJsonObject(InitialPropertiesJson);
    if (AssetPath.IsEmpty() || !AssetClass || !InitialProperties.IsValid())
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_asset_class_or_properties"));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "CreateKnownAssetByClassPath", "AIStudioBridge Create Known Asset By Class Path"));
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UObject* Asset = Package
        ? NewObject<UObject>(Package, AssetClass, FName(*AIStudioAssetNameFromAssetPath(AssetPath)), RF_Public | RF_Standalone | RF_Transactional)
        : nullptr;
    if (!Asset)
    {
        Root->SetStringField(TEXT("status"), TEXT("asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    Asset->Modify();
    TArray<FString> Errors;
    const bool bPropertiesApplied = AIStudioSetPropertiesFromJson(Asset, InitialProperties, Errors);
    FAssetRegistryModule::AssetCreated(Asset);
    const bool bSaved = AIStudioSaveAssetPackage(Asset);
    TArray<TSharedPtr<FJsonValue>> ErrorValues;
    for (const FString& Error : Errors)
    {
        ErrorValues.Add(MakeShared<FJsonValueString>(Error));
    }
    Root->SetArrayField(TEXT("property_errors"), ErrorValues);
    Root->SetBoolField(TEXT("ok"), bSaved && bPropertiesApplied && Errors.IsEmpty());
    Root->SetStringField(TEXT("status"), bSaved ? (Errors.IsEmpty() ? TEXT("created_and_saved") : TEXT("created_with_property_errors")) : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_name"), Asset->GetName());
    Root->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetPathName());
    Root->SetStringField(TEXT("saved_package"), PackageName);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectReflectedAsset(const FString& AssetPath, const TArray<FName>& PropertyNames)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_reflected_asset"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("asset_path"), AssetPath);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_reflected_asset(asset_path, property_names)"));

#if WITH_EDITOR
    UObject* Asset = AIStudioLoadAssetObject(AssetPath);
    if (!Asset)
    {
        Root->SetStringField(TEXT("status"), TEXT("asset_not_found"));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> Properties;
    if (PropertyNames.Num() > 0)
    {
        for (FName Name : PropertyNames)
        {
            if (FProperty* Property = Asset->GetClass()->FindPropertyByName(Name))
            {
                Properties.Add(MakeShared<FJsonValueObject>(AIStudioReflectedPropertyValue(Asset, Property)));
            }
        }
    }
    else
    {
        for (TFieldIterator<FProperty> It(Asset->GetClass()); It; ++It)
        {
            Properties.Add(MakeShared<FJsonValueObject>(AIStudioReflectedPropertyValue(Asset, *It)));
        }
    }
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("status"), TEXT("inspected"));
    Root->SetStringField(TEXT("asset_name"), Asset->GetName());
    Root->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetPathName());
    Root->SetArrayField(TEXT("properties"), Properties);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetReflectedAssetProperty(const FString& AssetPath, FName PropertyName, const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_reflected_asset_property"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("asset_path"), AssetPath);
    Root->SetStringField(TEXT("property_name"), PropertyName.ToString());
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_reflected_asset_property(asset_path, property_name, value_json)"));

#if WITH_EDITOR
    UObject* Asset = AIStudioLoadAssetObject(AssetPath);
    FProperty* Property = Asset ? Asset->GetClass()->FindPropertyByName(PropertyName) : nullptr;
    if (!Asset || !Property)
    {
        Root->SetStringField(TEXT("status"), Asset ? TEXT("property_not_found") : TEXT("asset_not_found"));
        return AIStudioJsonString(Root);
    }
    TSharedPtr<FJsonValue> ParsedValue;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ValueJson);
    if (!FJsonSerializer::Deserialize(Reader, ParsedValue) || !ParsedValue.IsValid())
    {
        ParsedValue = MakeShared<FJsonValueString>(ValueJson);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetReflectedAssetProperty", "AIStudioBridge Set Reflected Asset Property"));
    Asset->Modify();
    FString Error;
    const bool bApplied = AIStudioSetPropertyFromJsonValue(Asset, Property, ParsedValue.Get(), Error);
    const bool bSaved = bApplied && AIStudioSaveAssetPackage(Asset);
    Root->SetBoolField(TEXT("ok"), bApplied && bSaved);
    Root->SetStringField(TEXT("status"), bApplied ? (bSaved ? TEXT("property_set_and_saved") : TEXT("save_failed")) : TEXT("property_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetObjectField(TEXT("readback"), AIStudioReflectedPropertyValue(Asset, Property));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddObjectReferenceToReflectedArray(const FString& AssetPath, FName PropertyName, const FString& ObjectPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_object_reference_to_reflected_array"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("asset_path"), AssetPath);
    Root->SetStringField(TEXT("property_name"), PropertyName.ToString());
    Root->SetStringField(TEXT("object_path"), ObjectPath);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_object_reference_to_reflected_array(asset_path, property_name, object_path)"));

#if WITH_EDITOR
    UObject* Asset = AIStudioLoadAssetObject(AssetPath);
    UObject* Object = AIStudioLoadAssetObject(ObjectPath);
    FArrayProperty* ArrayProperty = Asset ? CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(PropertyName)) : nullptr;
    FObjectProperty* InnerObjectProperty = ArrayProperty ? CastField<FObjectProperty>(ArrayProperty->Inner) : nullptr;
    if (!Asset || !Object || !ArrayProperty || !InnerObjectProperty || !Object->IsA(InnerObjectProperty->PropertyClass))
    {
        Root->SetStringField(TEXT("status"), TEXT("unsupported_asset_object_or_array_property"));
        return AIStudioJsonString(Root);
    }
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "AddObjectReferenceToReflectedArray", "AIStudioBridge Add Object Reference To Reflected Array"));
    Asset->Modify();
    void* ArrayPtr = ArrayProperty->ContainerPtrToValuePtr<void>(Asset);
    FScriptArrayHelper Helper(ArrayProperty, ArrayPtr);
    const int32 Index = Helper.AddValue();
    InnerObjectProperty->SetObjectPropertyValue(Helper.GetRawPtr(Index), Object);
    const bool bSaved = AIStudioSaveAssetPackage(Asset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("reference_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("array_count"), Helper.Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemoveObjectReferenceFromReflectedArray(const FString& AssetPath, FName PropertyName, const FString& ObjectPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_object_reference_from_reflected_array"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("asset_path"), AssetPath);
    Root->SetStringField(TEXT("property_name"), PropertyName.ToString());
    Root->SetStringField(TEXT("object_path"), ObjectPath);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_object_reference_from_reflected_array(asset_path, property_name, object_path)"));

#if WITH_EDITOR
    UObject* Asset = AIStudioLoadAssetObject(AssetPath);
    UObject* Object = AIStudioLoadAssetObject(ObjectPath);
    FArrayProperty* ArrayProperty = Asset ? CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(PropertyName)) : nullptr;
    FObjectProperty* InnerObjectProperty = ArrayProperty ? CastField<FObjectProperty>(ArrayProperty->Inner) : nullptr;
    if (!Asset || !Object || !ArrayProperty || !InnerObjectProperty)
    {
        Root->SetStringField(TEXT("status"), TEXT("unsupported_asset_object_or_array_property"));
        return AIStudioJsonString(Root);
    }
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "RemoveObjectReferenceFromReflectedArray", "AIStudioBridge Remove Object Reference From Reflected Array"));
    Asset->Modify();
    void* ArrayPtr = ArrayProperty->ContainerPtrToValuePtr<void>(Asset);
    FScriptArrayHelper Helper(ArrayProperty, ArrayPtr);
    bool bRemoved = false;
    for (int32 Index = Helper.Num() - 1; Index >= 0; --Index)
    {
        if (InnerObjectProperty->GetObjectPropertyValue(Helper.GetRawPtr(Index)) == Object)
        {
            Helper.RemoveValues(Index);
            bRemoved = true;
        }
    }
    const bool bSaved = bRemoved && AIStudioSaveAssetPackage(Asset);
    Root->SetBoolField(TEXT("ok"), bRemoved && bSaved);
    Root->SetStringField(TEXT("status"), bRemoved ? (bSaved ? TEXT("reference_removed_and_saved") : TEXT("save_failed")) : TEXT("reference_not_found"));
    Root->SetNumberField(TEXT("array_count"), Helper.Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddAnimGraphState(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName StateName,
    UObject* AnimationAsset)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_anim_graph_state"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("state_name"), StateName.ToString());
    Root->SetStringField(TEXT("animation_asset"), AnimationAsset ? AnimationAsset->GetPathName() : TEXT(""));
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.add_anim_graph_state(anim_bp, state_machine, state_name, animation_asset)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    if (StateName.IsNone())
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_state_name"));
        Root->SetStringField(TEXT("error"), TEXT("StateName is required."));
        return AIStudioJsonString(Root);
    }

    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    if (!StateMachineGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_machine_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested state machine graph was not found."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "AddAnimGraphState", "AIStudioBridge Add Anim Graph State"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();

    UAnimStateNode* StateNode = AIStudioFindStateNode(StateMachineGraph, StateName);
    const bool bCreated = StateNode == nullptr;
    if (!StateNode)
    {
        const int32 NodeOffset = StateMachineGraph->Nodes.Num() * 120;
        StateNode = FEdGraphSchemaAction_NewStateNode::SpawnNodeFromTemplate<UAnimStateNode>(
            StateMachineGraph,
            NewObject<UAnimStateNode>(),
            FVector2f(300.0f + NodeOffset, 100.0f),
            false);
        if (!StateNode)
        {
            Root->SetStringField(TEXT("status"), TEXT("state_create_failed"));
            Root->SetStringField(TEXT("error"), TEXT("Unreal did not create the UAnimStateNode."));
            return AIStudioJsonString(Root);
        }
        FEdGraphUtilities::RenameGraphToNameOrCloseToName(StateNode->BoundGraph, StateName.ToString());
        StateNode->ReconstructNode();
    }

    bool bAnimationAssigned = false;
    if (UAnimSequenceBase* Sequence = Cast<UAnimSequenceBase>(AnimationAsset))
    {
        if (UEdGraphPin* PosePin = StateNode->GetPoseSinkPinInsideState())
        {
            StateNode->BoundGraph->Modify();
            UAnimGraphNode_SequencePlayer* SequencePlayer = nullptr;
            for (UEdGraphNode* ExistingNode : StateNode->BoundGraph->Nodes)
            {
                UAnimGraphNode_SequencePlayer* ExistingPlayer = Cast<UAnimGraphNode_SequencePlayer>(ExistingNode);
                if (ExistingPlayer && ExistingPlayer->Node.GetSequence() == Sequence)
                {
                    SequencePlayer = ExistingPlayer;
                    break;
                }
            }
            if (!SequencePlayer)
            {
                FGraphNodeCreator<UAnimGraphNode_SequencePlayer> NodeCreator(*StateNode->BoundGraph);
                SequencePlayer = NodeCreator.CreateNode();
                SequencePlayer->NodePosX = -300;
                SequencePlayer->NodePosY = 0;
                SequencePlayer->Node.SetSequence(Sequence);
                NodeCreator.Finalize();
                SequencePlayer->ReconstructNode();
            }

            if (UEdGraphPin* SequencePosePin = AIStudioFindPosePin(SequencePlayer, EGPD_Output))
            {
                bAnimationAssigned = PosePin->LinkedTo.Contains(SequencePosePin);
                const UEdGraphSchema* StateSchema = StateNode->BoundGraph->GetSchema();
                if (!bAnimationAssigned)
                {
                    bAnimationAssigned = StateSchema && StateSchema->TryCreateConnection(SequencePosePin, PosePin);
                }
            }
        }
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    const bool bAnimationRequired = AnimationAsset != nullptr;
    const bool bOperationOk = !bAnimationRequired || bAnimationAssigned;
    Root->SetBoolField(TEXT("ok"), bOperationOk);
    Root->SetStringField(
        TEXT("status"),
        bOperationOk
            ? (bCreated ? TEXT("created") : TEXT("already_exists"))
            : TEXT("state_created_animation_not_assigned"));
    Root->SetStringField(TEXT("state_graph"), StateNode->BoundGraph ? StateNode->BoundGraph->GetName() : TEXT(""));
    Root->SetBoolField(TEXT("animation_assigned"), bAnimationAssigned);
    Root->SetBoolField(TEXT("animation_required"), bAnimationRequired);
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddAnimGraphStateMachine(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_anim_graph_state_machine"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.add_anim_graph_state_machine(anim_bp, state_machine)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    if (StateMachineName.IsNone())
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_state_machine_name"));
        Root->SetStringField(TEXT("error"), TEXT("StateMachineName is required."));
        return AIStudioJsonString(Root);
    }

    UAnimGraphNode_StateMachineBase* ExistingNode = nullptr;
    UAnimationStateMachineGraph* ExistingGraph = AIStudioFindStateMachineGraph(
        AnimBlueprint,
        StateMachineName,
        &ExistingNode);
    if (ExistingGraph && ExistingNode)
    {
        Root->SetBoolField(TEXT("ok"), true);
        Root->SetStringField(TEXT("status"), TEXT("already_exists"));
        Root->SetStringField(TEXT("anim_graph"), ExistingNode->GetGraph()->GetName());
        Root->SetStringField(TEXT("state_machine_graph"), ExistingGraph->GetName());
        Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
        return AIStudioJsonString(Root);
    }

    TArray<UEdGraph*> Graphs;
    AnimBlueprint->GetAllGraphs(Graphs);
    UAnimationGraph* AnimGraph = nullptr;
    for (UEdGraph* Graph : Graphs)
    {
        UAnimationGraph* Candidate = Cast<UAnimationGraph>(Graph);
        if (!Candidate)
        {
            continue;
        }
        AnimGraph = Candidate;
        if (Candidate->GetName().Equals(TEXT("AnimGraph"), ESearchCase::IgnoreCase))
        {
            break;
        }
    }
    if (!AnimGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("anim_graph_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("No AnimationGraph was found on the AnimBlueprint."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(
        NSLOCTEXT("AIStudioBridge", "AddAnimGraphStateMachine", "AIStudioBridge Add Anim Graph State Machine"));
    AnimBlueprint->Modify();
    AnimGraph->Modify();
    FGraphNodeCreator<UAnimGraphNode_StateMachine> NodeCreator(*AnimGraph);
    UAnimGraphNode_StateMachine* StateMachineNode = NodeCreator.CreateNode();
    StateMachineNode->NodePosX = -300;
    StateMachineNode->NodePosY = 0;
    NodeCreator.Finalize();
    if (!StateMachineNode || !StateMachineNode->EditorStateMachineGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_machine_create_failed"));
        Root->SetStringField(TEXT("error"), TEXT("Unreal did not create the state-machine node and bound graph."));
        return AIStudioJsonString(Root);
    }

    FEdGraphUtilities::RenameGraphToNameOrCloseToName(
        StateMachineNode->EditorStateMachineGraph,
        StateMachineName.ToString());
    StateMachineNode->ReconstructNode();
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);

    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("status"), TEXT("created"));
    Root->SetStringField(TEXT("anim_graph"), AnimGraph->GetName());
    Root->SetStringField(
        TEXT("state_machine_graph"),
        StateMachineNode->EditorStateMachineGraph->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddAnimGraphTransitionRule(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName FromState,
    FName ToState,
    const FString& RuleExpression)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_anim_graph_transition_rule"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("from_state"), FromState.ToString());
    Root->SetStringField(TEXT("to_state"), ToState.ToString());
    Root->SetStringField(TEXT("rule_expression"), RuleExpression);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.add_anim_graph_transition_rule(anim_bp, state_machine, from_state, to_state, rule_expression)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    if (!StateMachineGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_machine_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested state machine graph was not found."));
        return AIStudioJsonString(Root);
    }
    UAnimStateNode* FromNode = AIStudioFindStateNode(StateMachineGraph, FromState);
    UAnimStateNode* ToNode = AIStudioFindStateNode(StateMachineGraph, ToState);
    if (!FromNode || !ToNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("Both source and destination states must exist before adding a transition."));
        Root->SetBoolField(TEXT("from_state_found"), FromNode != nullptr);
        Root->SetBoolField(TEXT("to_state_found"), ToNode != nullptr);
        return AIStudioJsonString(Root);
    }

    const FString NormalizedRule = RuleExpression.TrimStartAndEnd().ToLower();
    const bool bSupportedConstantRule = NormalizedRule.IsEmpty()
        || NormalizedRule == TEXT("true")
        || NormalizedRule == TEXT("false")
        || NormalizedRule == TEXT("always")
        || NormalizedRule == TEXT("never");
    if (!bSupportedConstantRule)
    {
        Root->SetStringField(TEXT("status"), TEXT("unsupported_rule_expression"));
        Root->SetStringField(TEXT("error"), TEXT("This wrapper currently supports constant transition rules only: true/always or false/never. Use a rule-graph synthesis capability for arbitrary Blueprint expressions."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "AddAnimGraphTransitionRule", "AIStudioBridge Add Anim Graph Transition Rule"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();

    UAnimStateTransitionNode* TransitionNode = AIStudioFindTransitionNode(StateMachineGraph, FromNode, ToNode);
    const bool bCreated = TransitionNode == nullptr;
    if (!TransitionNode)
    {
        const FVector2f Location = (FVector2f(FromNode->NodePosX, FromNode->NodePosY) + FVector2f(ToNode->NodePosX, ToNode->NodePosY)) * 0.5f;
        TransitionNode = FEdGraphSchemaAction_NewStateNode::SpawnNodeFromTemplate<UAnimStateTransitionNode>(
            StateMachineGraph,
            NewObject<UAnimStateTransitionNode>(),
            Location,
            false);
        if (!TransitionNode)
        {
            Root->SetStringField(TEXT("status"), TEXT("transition_create_failed"));
            Root->SetStringField(TEXT("error"), TEXT("Unreal did not create the UAnimStateTransitionNode."));
            return AIStudioJsonString(Root);
        }
        TransitionNode->CreateConnections(FromNode, ToNode);
    }

    bool bRuleApplied = false;
    bool bRuleValue = !(NormalizedRule == TEXT("false") || NormalizedRule == TEXT("never"));
    if (UAnimationTransitionGraph* TransitionGraph = Cast<UAnimationTransitionGraph>(TransitionNode->GetBoundGraph()))
    {
        if (UAnimGraphNode_TransitionResult* ResultNode = TransitionGraph->GetResultNode())
        {
            if (UEdGraphPin* CanEnterPin = ResultNode->FindPin(TEXT("bCanEnterTransition")))
            {
                CanEnterPin->Modify();
                CanEnterPin->DefaultValue = bRuleValue ? TEXT("true") : TEXT("false");
                bRuleApplied = true;
            }
        }
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    Root->SetBoolField(TEXT("ok"), bRuleApplied);
    Root->SetStringField(TEXT("status"), bRuleApplied ? (bCreated ? TEXT("created") : TEXT("already_exists")) : TEXT("rule_apply_failed"));
    Root->SetBoolField(TEXT("created"), bCreated);
    Root->SetBoolField(TEXT("rule_applied"), bRuleApplied);
    Root->SetBoolField(TEXT("constant_rule_value"), bRuleValue);
    Root->SetStringField(TEXT("transition_graph"), TransitionNode->GetBoundGraph() ? TransitionNode->GetBoundGraph()->GetName() : TEXT(""));
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::DeleteAnimGraphState(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName StateName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("delete_anim_graph_state"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("state_name"), StateName.ToString());
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.delete_anim_graph_state(anim_bp, state_machine, state_name)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    if (!StateMachineGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_machine_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested state machine graph was not found."));
        return AIStudioJsonString(Root);
    }
    UAnimStateNode* StateNode = AIStudioFindStateNode(StateMachineGraph, StateName);
    if (!StateNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested state was not found."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "DeleteAnimGraphState", "AIStudioBridge Delete Anim Graph State"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();
    const int32 BeforeCount = StateMachineGraph->Nodes.Num();
    FBlueprintEditorUtils::RemoveNode(AnimBlueprint, StateNode, true);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    const bool bRemoved = AIStudioFindStateNode(StateMachineGraph, StateName) == nullptr;
    Root->SetBoolField(TEXT("ok"), bRemoved);
    Root->SetStringField(TEXT("status"), bRemoved ? TEXT("deleted") : TEXT("delete_failed"));
    Root->SetNumberField(TEXT("node_count_before"), BeforeCount);
    Root->SetNumberField(TEXT("node_count_after"), StateMachineGraph->Nodes.Num());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::DeleteAnimGraphTransition(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName FromState,
    FName ToState)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("delete_anim_graph_transition"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("from_state"), FromState.ToString());
    Root->SetStringField(TEXT("to_state"), ToState.ToString());
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.delete_anim_graph_transition(anim_bp, state_machine, from_state, to_state)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    UAnimStateNode* FromNode = AIStudioFindStateNode(StateMachineGraph, FromState);
    UAnimStateNode* ToNode = AIStudioFindStateNode(StateMachineGraph, ToState);
    UAnimStateTransitionNode* TransitionNode = AIStudioFindTransitionNode(StateMachineGraph, FromNode, ToNode);
    if (!TransitionNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("transition_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested transition was not found."));
        Root->SetBoolField(TEXT("from_state_found"), FromNode != nullptr);
        Root->SetBoolField(TEXT("to_state_found"), ToNode != nullptr);
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "DeleteAnimGraphTransition", "AIStudioBridge Delete Anim Graph Transition"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();
    const int32 BeforeCount = StateMachineGraph->Nodes.Num();
    FBlueprintEditorUtils::RemoveNode(AnimBlueprint, TransitionNode, true);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    const bool bRemoved = AIStudioFindTransitionNode(StateMachineGraph, FromNode, ToNode) == nullptr;
    Root->SetBoolField(TEXT("ok"), bRemoved);
    Root->SetStringField(TEXT("status"), bRemoved ? TEXT("deleted") : TEXT("delete_failed"));
    Root->SetNumberField(TEXT("node_count_before"), BeforeCount);
    Root->SetNumberField(TEXT("node_count_after"), StateMachineGraph->Nodes.Num());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RenameAnimGraphState(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName OldStateName,
    FName NewStateName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("rename_anim_graph_state"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("old_state_name"), OldStateName.ToString());
    Root->SetStringField(TEXT("new_state_name"), NewStateName.ToString());
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.rename_anim_graph_state(anim_bp, state_machine, old_state_name, new_state_name)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    if (NewStateName.IsNone())
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_state_name"));
        Root->SetStringField(TEXT("error"), TEXT("NewStateName is required."));
        return AIStudioJsonString(Root);
    }
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    UAnimStateNode* StateNode = AIStudioFindStateNode(StateMachineGraph, OldStateName);
    if (!StateNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested source state was not found."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "RenameAnimGraphState", "AIStudioBridge Rename Anim Graph State"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();
    StateNode->Modify();
    if (StateNode->BoundGraph)
    {
        StateNode->BoundGraph->Modify();
        FEdGraphUtilities::RenameGraphToNameOrCloseToName(StateNode->BoundGraph, NewStateName.ToString());
    }
    StateNode->ReconstructNode();
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    const bool bRenamed = AIStudioFindStateNode(StateMachineGraph, NewStateName) == StateNode;
    Root->SetBoolField(TEXT("ok"), bRenamed);
    Root->SetStringField(TEXT("status"), bRenamed ? TEXT("renamed") : TEXT("rename_failed"));
    Root->SetStringField(TEXT("readback_state_name"), StateNode->GetStateName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetAnimGraphTransitionRule(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName FromState,
    FName ToState,
    const FString& RuleExpression)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_anim_graph_transition_rule"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("from_state"), FromState.ToString());
    Root->SetStringField(TEXT("to_state"), ToState.ToString());
    Root->SetStringField(TEXT("rule_expression"), RuleExpression);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.set_anim_graph_transition_rule(anim_bp, state_machine, from_state, to_state, rule_expression)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    UAnimStateNode* FromNode = AIStudioFindStateNode(StateMachineGraph, FromState);
    UAnimStateNode* ToNode = AIStudioFindStateNode(StateMachineGraph, ToState);
    UAnimStateTransitionNode* TransitionNode = AIStudioFindTransitionNode(StateMachineGraph, FromNode, ToNode);
    if (!TransitionNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("transition_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested transition was not found."));
        Root->SetBoolField(TEXT("from_state_found"), FromNode != nullptr);
        Root->SetBoolField(TEXT("to_state_found"), ToNode != nullptr);
        return AIStudioJsonString(Root);
    }

    const FString NormalizedRule = RuleExpression.TrimStartAndEnd().ToLower();
    const bool bSupportedConstantRule = NormalizedRule.IsEmpty()
        || NormalizedRule == TEXT("true")
        || NormalizedRule == TEXT("false")
        || NormalizedRule == TEXT("always")
        || NormalizedRule == TEXT("never");
    if (!bSupportedConstantRule)
    {
        Root->SetStringField(TEXT("status"), TEXT("unsupported_rule_expression"));
        Root->SetStringField(TEXT("error"), TEXT("This wrapper currently supports constant transition rules only. Use a rule-graph synthesis capability for arbitrary Blueprint expressions."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetAnimGraphTransitionRule", "AIStudioBridge Set Anim Graph Transition Rule"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();
    TransitionNode->Modify();
    bool bRuleApplied = false;
    const bool bRuleValue = !(NormalizedRule == TEXT("false") || NormalizedRule == TEXT("never"));
    if (UAnimationTransitionGraph* TransitionGraph = Cast<UAnimationTransitionGraph>(TransitionNode->GetBoundGraph()))
    {
        TransitionGraph->Modify();
        if (UAnimGraphNode_TransitionResult* ResultNode = TransitionGraph->GetResultNode())
        {
            ResultNode->Modify();
            if (UEdGraphPin* CanEnterPin = ResultNode->FindPin(TEXT("bCanEnterTransition")))
            {
                CanEnterPin->Modify();
                CanEnterPin->DefaultValue = bRuleValue ? TEXT("true") : TEXT("false");
                bRuleApplied = true;
            }
        }
    }
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    Root->SetBoolField(TEXT("ok"), bRuleApplied);
    Root->SetStringField(TEXT("status"), bRuleApplied ? TEXT("rule_applied") : TEXT("rule_apply_failed"));
    Root->SetBoolField(TEXT("constant_rule_value"), bRuleValue);
    Root->SetStringField(TEXT("transition_graph"), TransitionNode->GetBoundGraph() ? TransitionNode->GetBoundGraph()->GetName() : TEXT(""));
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SynthesizeAnimGraphTransitionRuleExpression(
    UAnimBlueprint* AnimBlueprint,
    FName StateMachineName,
    FName FromState,
    FName ToState,
    const FString& RuleExpression)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("synthesize_anim_graph_transition_rule_expression"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(TEXT("from_state"), FromState.ToString());
    Root->SetStringField(TEXT("to_state"), ToState.ToString());
    Root->SetStringField(TEXT("rule_expression"), RuleExpression);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.synthesize_anim_graph_transition_rule_expression(anim_bp, state_machine, from_state, to_state, rule_expression)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(AnimBlueprint, StateMachineName);
    UAnimStateNode* FromNode = AIStudioFindStateNode(StateMachineGraph, FromState);
    UAnimStateNode* ToNode = AIStudioFindStateNode(StateMachineGraph, ToState);
    UAnimStateTransitionNode* TransitionNode = AIStudioFindTransitionNode(StateMachineGraph, FromNode, ToNode);
    if (!TransitionNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("transition_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested transition was not found. Create the transition edge before synthesizing its rule graph."));
        Root->SetBoolField(TEXT("from_state_found"), FromNode != nullptr);
        Root->SetBoolField(TEXT("to_state_found"), ToNode != nullptr);
        return AIStudioJsonString(Root);
    }
    UAnimationTransitionGraph* TransitionGraph = Cast<UAnimationTransitionGraph>(TransitionNode->GetBoundGraph());
    if (!TransitionGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("transition_graph_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The transition node did not expose a transition graph."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SynthesizeAnimGraphTransitionRuleExpression", "AIStudioBridge Synthesize Anim Graph Transition Rule Expression"));
    AnimBlueprint->Modify();
    StateMachineGraph->Modify();
    TransitionNode->Modify();
    TransitionGraph->Modify();

    bool bApplied = false;
    bool bConstantValue = false;
    int32 CreatedNodeCount = 0;
    FString FinalSourceNode;
    TArray<FString> UnsupportedReasons;
    const FString NormalizedRule = RuleExpression.TrimStartAndEnd().ToLower();
    if (UAnimGraphNode_TransitionResult* ResultNode = TransitionGraph->GetResultNode())
    {
        bApplied = AIStudioApplyConstantTransitionRule(ResultNode, NormalizedRule, bConstantValue);
    }
    if (!bApplied)
    {
        bApplied = AIStudioSynthesizeTransitionRuleGraph(
            TransitionGraph,
            RuleExpression,
            UnsupportedReasons,
            CreatedNodeCount,
            FinalSourceNode);
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
    Root->SetBoolField(TEXT("ok"), bApplied);
    Root->SetStringField(TEXT("status"), bApplied ? TEXT("rule_graph_synthesized") : TEXT("unsupported_rule_expression"));
    Root->SetBoolField(TEXT("constant_rule"), bApplied && CreatedNodeCount == 0);
    Root->SetBoolField(TEXT("constant_rule_value"), bConstantValue);
    Root->SetNumberField(TEXT("created_node_count"), CreatedNodeCount);
    Root->SetStringField(TEXT("final_source_node"), FinalSourceNode);
    Root->SetStringField(TEXT("transition_graph"), TransitionGraph->GetName());
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
    TArray<TSharedPtr<FJsonValue>> ReasonValues;
    for (const FString& Reason : UnsupportedReasons)
    {
        ReasonValues.Add(MakeShared<FJsonValueString>(Reason));
    }
    Root->SetArrayField(TEXT("unsupported_reasons"), ReasonValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::WireAnimGraphOutputPose(UAnimBlueprint* AnimBlueprint, FName StateMachineName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("wire_anim_graph_output_pose"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("state_machine"), StateMachineName.ToString());
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.wire_anim_graph_output_pose(anim_bp, state_machine)"));

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_target"));
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }

    UAnimGraphNode_StateMachineBase* StateMachineNode = nullptr;
    UAnimationStateMachineGraph* StateMachineGraph = AIStudioFindStateMachineGraph(
        AnimBlueprint,
        StateMachineName,
        &StateMachineNode);
    if (!StateMachineGraph || !StateMachineNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("state_machine_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The requested state machine node was not found in an AnimGraph."));
        return AIStudioJsonString(Root);
    }

    UAnimationGraph* AnimGraph = AIStudioFindAnimationGraphForNode(StateMachineNode);
    if (!AnimGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("anim_graph_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("The owning AnimGraph for the state machine node was not found."));
        return AIStudioJsonString(Root);
    }

    UAnimGraphNode_Root* RootNode = nullptr;
    for (UEdGraphNode* Node : AnimGraph->Nodes)
    {
        RootNode = Cast<UAnimGraphNode_Root>(Node);
        if (RootNode)
        {
            break;
        }
    }
    if (!RootNode)
    {
        Root->SetStringField(TEXT("status"), TEXT("output_pose_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("No AnimGraph output pose root node was found."));
        return AIStudioJsonString(Root);
    }

    UEdGraphPin* MachinePosePin = AIStudioFindPosePin(StateMachineNode, EGPD_Output);
    UEdGraphPin* OutputPosePin = AIStudioFindPosePin(RootNode, EGPD_Input);
    if (!MachinePosePin || !OutputPosePin)
    {
        Root->SetStringField(TEXT("status"), TEXT("pose_pin_not_found"));
        Root->SetStringField(TEXT("error"), TEXT("Could not resolve compatible pose pins on the state machine and output pose nodes."));
        Root->SetBoolField(TEXT("machine_pose_pin_found"), MachinePosePin != nullptr);
        Root->SetBoolField(TEXT("output_pose_pin_found"), OutputPosePin != nullptr);
        return AIStudioJsonString(Root);
    }

    const bool bAlreadyLinked = OutputPosePin->LinkedTo.Contains(MachinePosePin);
    bool bLinked = bAlreadyLinked;
    if (!bAlreadyLinked)
    {
        const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "WireAnimGraphOutputPose", "AIStudioBridge Wire Anim Graph Output Pose"));
        AnimBlueprint->Modify();
        AnimGraph->Modify();
        StateMachineNode->Modify();
        RootNode->Modify();
        MachinePosePin->Modify();
        OutputPosePin->Modify();
        OutputPosePin->BreakAllPinLinks();
        const UEdGraphSchema* Schema = AnimGraph->GetSchema();
        bLinked = Schema && Schema->TryCreateConnection(MachinePosePin, OutputPosePin);
        if (bLinked)
        {
            FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(AnimBlueprint);
        }
    }

    Root->SetBoolField(TEXT("ok"), bLinked);
    Root->SetStringField(TEXT("status"), bLinked ? (bAlreadyLinked ? TEXT("already_linked") : TEXT("linked")) : TEXT("link_failed"));
    Root->SetStringField(TEXT("anim_graph"), AnimGraph->GetName());
    Root->SetStringField(TEXT("state_machine_graph"), StateMachineGraph->GetName());
    Root->SetStringField(TEXT("machine_pose_pin"), MachinePosePin->PinName.ToString());
    Root->SetStringField(TEXT("output_pose_pin"), OutputPosePin->PinName.ToString());
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CompileAndSaveAnimBlueprint(UAnimBlueprint* AnimBlueprint)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("compile_and_save_anim_blueprint"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }

    FKismetEditorUtilities::CompileBlueprint(AnimBlueprint);
    UPackage* Package = AnimBlueprint->GetOutermost();
    bool bSaved = false;
    if (Package)
    {
        Package->SetDirtyFlag(true);
        const FString PackageFileName = FPackageName::LongPackageNameToFilename(
            Package->GetName(),
            FPackageName::GetAssetPackageExtension());
        if (!PackageFileName.IsEmpty())
        {
            FSavePackageArgs SaveArgs;
            SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
            bSaved = UPackage::SavePackage(Package, AnimBlueprint, *PackageFileName, SaveArgs);
        }
    }

    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("compiled_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());
    Root->SetBoolField(TEXT("save_attempted"), Package != nullptr);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.compile_and_save_anim_blueprint(anim_bp)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif

    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectAnimationSequence(UAnimSequence* Animation)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_animation_sequence"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_animation_sequence(animation)"));
    if (!Animation)
    {
        Root->SetStringField(TEXT("error"), TEXT("Animation was null."));
        return AIStudioJsonString(Root);
    }

    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("asset_name"), Animation->GetName());
    Root->SetStringField(TEXT("asset_path"), Animation->GetPathName());
    Root->SetStringField(TEXT("skeleton"), Animation->GetSkeleton() ? Animation->GetSkeleton()->GetPathName() : TEXT(""));
    Root->SetNumberField(TEXT("play_length_seconds"), Animation->GetPlayLength());
    Root->SetNumberField(TEXT("sampled_keys"), Animation->GetNumberOfSampledKeys());
    Root->SetNumberField(TEXT("sample_rate_fps"), Animation->GetSamplingFrameRate().AsDecimal());
    Root->SetBoolField(TEXT("has_root_motion"), Animation->HasRootMotion());
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::ConfigureBlendSpace(
    UBlendSpace* BlendSpace,
    const FString& SamplesJson,
    const FString& AxisXJson,
    const FString& AxisYJson,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
#if WITH_EDITOR
    if (!BlendSpace)
    {
        Root->SetBoolField(TEXT("ok"), false);
        Root->SetStringField(TEXT("status"), TEXT("blendspace_missing"));
        return AIStudioJsonString(Root);
    }

    FString AxisError;
    FBlendParameter AxisX = BlendSpace->GetBlendParameter(0);
    FBlendParameter AxisY = BlendSpace->GetBlendParameter(1);
    if (!AIStudioApplyBlendParameterJson(AxisXJson, AxisX, AxisError)
        || !AIStudioApplyBlendParameterJson(AxisYJson, AxisY, AxisError))
    {
        Root->SetBoolField(TEXT("ok"), false);
        Root->SetStringField(TEXT("status"), TEXT("invalid_axis_settings"));
        Root->SetStringField(TEXT("error"), AxisError);
        return AIStudioJsonString(Root);
    }

    TArray<TSharedPtr<FJsonValue>> RequestedSamples;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(SamplesJson);
    if (!FJsonSerializer::Deserialize(Reader, RequestedSamples))
    {
        Root->SetBoolField(TEXT("ok"), false);
        Root->SetStringField(TEXT("status"), TEXT("invalid_samples_json"));
        return AIStudioJsonString(Root);
    }

    struct FPendingBlendSample
    {
        UAnimSequence* Animation = nullptr;
        FVector Position = FVector::ZeroVector;
    };
    TArray<FPendingBlendSample> Pending;
    TArray<TSharedPtr<FJsonValue>> Rejected;
    for (int32 Index = 0; Index < RequestedSamples.Num(); ++Index)
    {
        const TSharedPtr<FJsonObject> Row =
            RequestedSamples[Index].IsValid() ? RequestedSamples[Index]->AsObject() : nullptr;
        FString AnimationPath;
        if (Row.IsValid())
        {
            if (!Row->TryGetStringField(TEXT("animation_path"), AnimationPath))
            {
                Row->TryGetStringField(TEXT("animation"), AnimationPath);
            }
        }
        UAnimSequence* Animation = AnimationPath.IsEmpty()
            ? nullptr
            : LoadObject<UAnimSequence>(nullptr, *AnimationPath);
        FVector Position = FVector::ZeroVector;
        const TArray<TSharedPtr<FJsonValue>>* PositionValues = nullptr;
        if (Row.IsValid()
            && Row->TryGetArrayField(TEXT("position"), PositionValues)
            && PositionValues
            && PositionValues->Num() >= 2)
        {
            Position.X = static_cast<float>((*PositionValues)[0]->AsNumber());
            Position.Y = static_cast<float>((*PositionValues)[1]->AsNumber());
            Position.Z = PositionValues->Num() >= 3
                ? static_cast<float>((*PositionValues)[2]->AsNumber())
                : 0.0f;
        }
        else if (Row.IsValid())
        {
            double Number = 0.0;
            if (Row->TryGetNumberField(TEXT("x"), Number))
            {
                Position.X = static_cast<float>(Number);
            }
            if (Row->TryGetNumberField(TEXT("y"), Number))
            {
                Position.Y = static_cast<float>(Number);
            }
            if (Row->TryGetNumberField(TEXT("z"), Number))
            {
                Position.Z = static_cast<float>(Number);
            }
        }

        FString Reason;
        if (!Animation)
        {
            Reason = TEXT("animation_not_found");
        }
        else if (!BlendSpace->IsAnimationCompatible(Animation))
        {
            Reason = TEXT("animation_incompatible");
        }
        if (!Reason.IsEmpty())
        {
            const TSharedRef<FJsonObject> Rejection = MakeShared<FJsonObject>();
            Rejection->SetNumberField(TEXT("index"), Index);
            Rejection->SetStringField(TEXT("animation_path"), AnimationPath);
            Rejection->SetStringField(TEXT("reason"), Reason);
            Rejected.Add(MakeShared<FJsonValueObject>(Rejection));
            continue;
        }
        Pending.Add({Animation, Position});
    }
    if (Rejected.Num() > 0)
    {
        Root->SetBoolField(TEXT("ok"), false);
        Root->SetStringField(TEXT("status"), TEXT("sample_validation_failed"));
        Root->SetArrayField(TEXT("rejected_samples"), Rejected);
        return AIStudioJsonString(Root);
    }

    BlendSpace->Modify();
    FStructProperty* BlendParametersProperty = FindFProperty<FStructProperty>(
        UBlendSpace::StaticClass(),
        TEXT("BlendParameters"));
    if (!BlendParametersProperty || BlendParametersProperty->ArrayDim < 2)
    {
        Root->SetBoolField(TEXT("ok"), false);
        Root->SetStringField(TEXT("status"), TEXT("blend_parameters_property_unavailable"));
        return AIStudioJsonString(Root);
    }
    *BlendParametersProperty->ContainerPtrToValuePtr<FBlendParameter>(BlendSpace, 0) = AxisX;
    *BlendParametersProperty->ContainerPtrToValuePtr<FBlendParameter>(BlendSpace, 1) = AxisY;
    TArray<TSharedPtr<FJsonValue>> Added;
    for (const FPendingBlendSample& PendingSample : Pending)
    {
        int32 SampleIndex = INDEX_NONE;
        const TArray<FBlendSample>& ExistingSamples = BlendSpace->GetBlendSamples();
        for (int32 Index = 0; Index < ExistingSamples.Num(); ++Index)
        {
            if (ExistingSamples[Index].Animation == PendingSample.Animation
                && ExistingSamples[Index].SampleValue.Equals(PendingSample.Position))
            {
                SampleIndex = Index;
                break;
            }
        }
        const bool bAlreadyExisted = SampleIndex != INDEX_NONE;
        if (!bAlreadyExisted)
        {
            SampleIndex = BlendSpace->AddSample(PendingSample.Animation, PendingSample.Position);
        }
        if (SampleIndex == INDEX_NONE)
        {
            Root->SetBoolField(TEXT("ok"), false);
            Root->SetStringField(TEXT("status"), TEXT("add_sample_failed"));
            Root->SetStringField(TEXT("animation_path"), PendingSample.Animation->GetPathName());
            return AIStudioJsonString(Root);
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("index"), SampleIndex);
        Row->SetStringField(TEXT("animation_path"), PendingSample.Animation->GetPathName());
        Row->SetNumberField(TEXT("x"), PendingSample.Position.X);
        Row->SetNumberField(TEXT("y"), PendingSample.Position.Y);
        Row->SetNumberField(TEXT("z"), PendingSample.Position.Z);
        Row->SetBoolField(TEXT("already_existed"), bAlreadyExisted);
        Added.Add(MakeShared<FJsonValueObject>(Row));
    }
    BlendSpace->ValidateSampleData();
    BlendSpace->PostEditChange();
    const bool bSaved = !bSave || AIStudioSaveAssetPackage(BlendSpace);

    TArray<TSharedPtr<FJsonValue>> Readback;
    for (int32 Index = 0; Index < BlendSpace->GetBlendSamples().Num(); ++Index)
    {
        const FBlendSample& Sample = BlendSpace->GetBlendSamples()[Index];
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("index"), Index);
        Row->SetStringField(
            TEXT("animation_path"),
            Sample.Animation ? Sample.Animation->GetPathName() : TEXT(""));
        Row->SetNumberField(TEXT("x"), Sample.SampleValue.X);
        Row->SetNumberField(TEXT("y"), Sample.SampleValue.Y);
        Row->SetNumberField(TEXT("z"), Sample.SampleValue.Z);
        Row->SetBoolField(TEXT("valid"), BlendSpace->IsValidBlendSampleIndex(Index));
        Readback.Add(MakeShared<FJsonValueObject>(Row));
    }
    Root->SetBoolField(TEXT("ok"), bSaved && Readback.Num() >= Pending.Num());
    Root->SetStringField(
        TEXT("status"),
        bSaved ? TEXT("configured_and_read_back") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), BlendSpace->GetPathName());
    Root->SetNumberField(TEXT("requested_sample_count"), RequestedSamples.Num());
    Root->SetNumberField(TEXT("sample_count"), Readback.Num());
    Root->SetArrayField(TEXT("samples_added"), Added);
    Root->SetArrayField(TEXT("samples"), Readback);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.configure_blend_space(blend_space, samples_json, axis_x_json, axis_y_json, save)"));
#else
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectCharacterInPIE(UClass* CharacterClass, FString ExpectedAnimClassContains, const TArray<FName>& PropertyNames)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_character_in_pie"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!GEditor || !GEditor->PlayWorld || !CharacterClass)
    {
        Root->SetStringField(TEXT("error"), TEXT("Active PIE world and CharacterClass are required."));
        return AIStudioJsonString(Root);
    }

    AActor* RuntimeActor = nullptr;
    for (TActorIterator<AActor> It(GEditor->PlayWorld); It; ++It)
    {
        if (*It && It->IsA(CharacterClass))
        {
            RuntimeActor = *It;
            break;
        }
    }
    if (!RuntimeActor)
    {
        Root->SetStringField(TEXT("error"), TEXT("No runtime actor of CharacterClass was found in PIE."));
        return AIStudioJsonString(Root);
    }

    Root->SetStringField(TEXT("actor"), RuntimeActor->GetName());
    Root->SetStringField(TEXT("actor_class"), RuntimeActor->GetClass()->GetPathName());
    Root->SetStringField(TEXT("location"), RuntimeActor->GetActorLocation().ToString());
    Root->SetStringField(TEXT("velocity"), RuntimeActor->GetVelocity().ToString());

    if (const ACharacter* Character = Cast<ACharacter>(RuntimeActor))
    {
        if (const UCharacterMovementComponent* Movement = Character->GetCharacterMovement())
        {
            Root->SetStringField(TEXT("movement_mode"), Movement->GetMovementName());
            Root->SetNumberField(TEXT("gravity_scale"), Movement->GravityScale);
        }
    }

    UAnimInstance* SelectedAnimInstance = nullptr;
    TArray<USkeletalMeshComponent*> Meshes;
    RuntimeActor->GetComponents(Meshes);
    for (USkeletalMeshComponent* Mesh : Meshes)
    {
        UAnimInstance* Instance = Mesh ? Mesh->GetAnimInstance() : nullptr;
        const FString ClassPath = Instance ? Instance->GetClass()->GetPathName() : TEXT("");
        if (Instance && (ExpectedAnimClassContains.IsEmpty() || ClassPath.Contains(ExpectedAnimClassContains)))
        {
            SelectedAnimInstance = Instance;
            Root->SetStringField(TEXT("anim_class"), ClassPath);
            if (UAnimMontage* ActiveMontage = Instance->GetCurrentActiveMontage())
            {
                Root->SetStringField(TEXT("active_montage"), ActiveMontage->GetPathName());
                Root->SetNumberField(TEXT("active_montage_position"), Instance->Montage_GetPosition(ActiveMontage));
            }
            break;
        }
    }

    const TSharedRef<FJsonObject> Properties = MakeShared<FJsonObject>();
    const TSharedRef<FJsonObject> PropertyOwners = MakeShared<FJsonObject>();
    for (const FName PropertyName : PropertyNames)
    {
        UObject* Owner = RuntimeActor;
        FProperty* Property = FindFProperty<FProperty>(Owner->GetClass(), PropertyName);
        if (!Property)
        {
            TInlineComponentArray<UActorComponent*> Components(RuntimeActor);
            for (UActorComponent* Component : Components)
            {
                if (!Component)
                {
                    continue;
                }
                Property = FindFProperty<FProperty>(Component->GetClass(), PropertyName);
                if (Property)
                {
                    Owner = Component;
                    break;
                }
            }
        }
        if (!Property && SelectedAnimInstance)
        {
            Owner = SelectedAnimInstance;
            Property = FindFProperty<FProperty>(Owner->GetClass(), PropertyName);
        }
        if (!Property)
        {
            Properties->SetStringField(PropertyName.ToString(), TEXT("<missing>"));
            PropertyOwners->SetStringField(PropertyName.ToString(), TEXT("<missing>"));
            continue;
        }
        FString Value;
        Property->ExportTextItem_Direct(Value, Property->ContainerPtrToValuePtr<void>(Owner), nullptr, Owner, PPF_None);
        Properties->SetStringField(PropertyName.ToString(), Value);
        PropertyOwners->SetStringField(PropertyName.ToString(), Owner->GetPathName());
    }
    Root->SetObjectField(TEXT("properties"), Properties);
    Root->SetObjectField(TEXT("property_owners"), PropertyOwners);
    Root->SetBoolField(TEXT("anim_instance_matched"), SelectedAnimInstance != nullptr);
    Root->SetBoolField(TEXT("ok"), SelectedAnimInstance != nullptr || ExpectedAnimClassContains.IsEmpty());
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_character_in_pie(character_class, expected_anim_class_contains, property_names)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::ValidateCharacterMontagesInPIE(UClass* CharacterClass, const TArray<UAnimMontage*>& Montages, FString ExpectedAnimClassContains)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("validate_character_montages_in_pie"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!GEditor || !GEditor->PlayWorld)
    {
        Root->SetStringField(TEXT("error"), TEXT("No active PIE world was found."));
        return AIStudioJsonString(Root);
    }
    if (!CharacterClass)
    {
        Root->SetStringField(TEXT("error"), TEXT("CharacterClass was null."));
        return AIStudioJsonString(Root);
    }

    UWorld* World = GEditor->PlayWorld;
    Root->SetStringField(TEXT("world"), World ? World->GetName() : TEXT(""));
    Root->SetStringField(TEXT("character_class"), CharacterClass->GetPathName());

    AActor* RuntimeActor = nullptr;
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* Candidate = *It;
        if (Candidate && Candidate->IsA(CharacterClass))
        {
            RuntimeActor = Candidate;
            break;
        }
    }

    if (!RuntimeActor)
    {
        Root->SetStringField(TEXT("error"), TEXT("No runtime actor of CharacterClass was found in PIE."));
        return AIStudioJsonString(Root);
    }
    Root->SetStringField(TEXT("actor"), RuntimeActor->GetName());
    Root->SetStringField(TEXT("actor_class"), RuntimeActor->GetClass()->GetPathName());

    TArray<USkeletalMeshComponent*> Meshes;
    RuntimeActor->GetComponents(Meshes);

    UAnimInstance* SelectedAnimInstance = nullptr;
    TArray<TSharedPtr<FJsonValue>> ComponentValues;
    for (USkeletalMeshComponent* Mesh : Meshes)
    {
        if (!Mesh)
        {
            continue;
        }
        UAnimInstance* AnimInstance = Mesh->GetAnimInstance();
        const FString AnimClassPath = AnimInstance ? AnimInstance->GetClass()->GetPathName() : TEXT("");
        const bool bMatchesExpected = ExpectedAnimClassContains.IsEmpty() || AnimClassPath.Contains(ExpectedAnimClassContains);

        const TSharedRef<FJsonObject> ComponentObject = MakeShared<FJsonObject>();
        ComponentObject->SetStringField(TEXT("name"), Mesh->GetName());
        ComponentObject->SetStringField(TEXT("skeletal_mesh"), Mesh->GetSkeletalMeshAsset() ? Mesh->GetSkeletalMeshAsset()->GetPathName() : TEXT(""));
        ComponentObject->SetStringField(TEXT("anim_class"), AnimClassPath);
        ComponentObject->SetBoolField(TEXT("matches_expected_anim_class"), bMatchesExpected);
        ComponentValues.Add(MakeShared<FJsonValueObject>(ComponentObject));

        if (!SelectedAnimInstance && AnimInstance && bMatchesExpected)
        {
            SelectedAnimInstance = AnimInstance;
        }
    }
    Root->SetArrayField(TEXT("components"), ComponentValues);

    if (!SelectedAnimInstance)
    {
        Root->SetStringField(TEXT("error"), TEXT("No runtime AnimInstance matched ExpectedAnimClassContains."));
        return AIStudioJsonString(Root);
    }
    Root->SetStringField(TEXT("selected_anim_class"), SelectedAnimInstance->GetClass()->GetPathName());

    bool bAllMontagesPlayable = Montages.Num() > 0;
    TArray<TSharedPtr<FJsonValue>> MontageValues;
    for (UAnimMontage* Montage : Montages)
    {
        const TSharedRef<FJsonObject> MontageObject = MakeShared<FJsonObject>();
        MontageObject->SetBoolField(TEXT("asset_exists"), Montage != nullptr);
        MontageObject->SetStringField(TEXT("asset_path"), Montage ? Montage->GetPathName() : TEXT(""));
        float PlayResult = 0.0f;
        bool bActive = false;
        bool bPlaying = false;
        if (Montage)
        {
            PlayResult = SelectedAnimInstance->Montage_Play(Montage, 1.0f);
            bActive = SelectedAnimInstance->Montage_IsActive(Montage);
            bPlaying = SelectedAnimInstance->Montage_IsPlaying(Montage);
            SelectedAnimInstance->Montage_Stop(0.0f, Montage);
        }
        MontageObject->SetNumberField(TEXT("play_result"), PlayResult);
        MontageObject->SetBoolField(TEXT("active_after_play"), bActive);
        MontageObject->SetBoolField(TEXT("playing_after_play"), bPlaying);
        const bool bPlayable = Montage && PlayResult > 0.0f && (bActive || bPlaying);
        MontageObject->SetBoolField(TEXT("playable"), bPlayable);
        bAllMontagesPlayable = bAllMontagesPlayable && bPlayable;
        MontageValues.Add(MakeShared<FJsonValueObject>(MontageObject));
    }
    Root->SetArrayField(TEXT("montages"), MontageValues);
    Root->SetBoolField(TEXT("ok"), bAllMontagesPlayable);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.validate_character_montages_in_pie(character_class, montages, expected_anim_class_contains)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif

    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InjectKeyInPIE(FKey Key, bool bPressed)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inject_key_in_pie"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("key"), Key.ToString());
    Root->SetBoolField(TEXT("pressed"), bPressed);

#if WITH_EDITOR
    if (!GEditor || !GEditor->PlayWorld)
    {
        Root->SetStringField(TEXT("error"), TEXT("No active PIE world was found."));
        return AIStudioJsonString(Root);
    }
    APlayerController* Controller = GEditor->PlayWorld->GetFirstPlayerController();
    if (!Controller)
    {
        Root->SetStringField(TEXT("error"), TEXT("No PIE player controller was found."));
        return AIStudioJsonString(Root);
    }
    const EInputEvent Event = bPressed ? IE_Pressed : IE_Released;
    const FInputKeyEventArgs InputParams = FInputKeyEventArgs::CreateSimulated(
        Key,
        Event,
        bPressed ? 1.0f : 0.0f);
    const bool bHandled = Controller->InputKey(InputParams);
    Root->SetStringField(TEXT("controller"), Controller->GetPathName());
    Root->SetBoolField(TEXT("handled"), bHandled);
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inject_key_in_pie(key, pressed)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::DescribeBlueprintNodeAction(
    UBlueprint* Blueprint,
    FName GraphName,
    const FString& NodeWithCategory)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("describe_blueprint_node_action"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("graph_name"), GraphName.ToString());
    Root->SetStringField(TEXT("palette_action"), NodeWithCategory);

#if WITH_EDITOR
    if (!Blueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("Blueprint was null."));
        return AIStudioJsonString(Root);
    }

    UEdGraph* SourceGraph = nullptr;
    TArray<UEdGraph*> Graphs;
    Graphs.Append(Blueprint->UbergraphPages);
    Graphs.Append(Blueprint->FunctionGraphs);
    Graphs.Append(Blueprint->MacroGraphs);
    Graphs.Append(Blueprint->DelegateSignatureGraphs);
    for (UEdGraph* Graph : Graphs)
    {
        if (Graph && Graph->GetFName() == GraphName)
        {
            SourceGraph = Graph;
            break;
        }
    }
    if (!SourceGraph)
    {
        Root->SetStringField(TEXT("error"), TEXT("The requested graph was not found."));
        return AIStudioJsonString(Root);
    }

    const int32 OriginalNodeCount = SourceGraph->Nodes.Num();
    const bool bPackageDirtyBefore = Blueprint->GetOutermost()->IsDirty();
    FBlueprintActionFilter Filter;
    FBlueprintActionContext& FilterContext = Filter.Context;
    FilterContext.Graphs.Add(SourceGraph);
    FilterContext.Blueprints.Add(Blueprint);

    TArray<TSharedPtr<FJsonValue>> MatchValues;
    const FBlueprintActionDatabase::FActionRegistry& Registry =
        FBlueprintActionDatabase::Get().GetAllActions();
    for (auto Iterator(Registry.CreateConstIterator()); Iterator; ++Iterator)
    {
        UObject* ActionObject = Iterator->Key.ResolveObjectPtr();
        if (!ActionObject)
        {
            continue;
        }
        for (const UBlueprintNodeSpawner* Spawner : Iterator->Value)
        {
            if (!Spawner)
            {
                continue;
            }
            FBlueprintActionInfo ActionInfo(ActionObject, Spawner);
            if (Filter.IsFiltered(ActionInfo))
            {
                continue;
            }
            const FBlueprintActionUiSpec UiSpec = Spawner->GetUiSpec(
                FilterContext,
                ActionInfo.GetBindings());
            const FString QualifiedName = FString::Printf(
                TEXT("%s|%s"),
                *UiSpec.Category.ToString().Replace(TEXT(" "), TEXT("")),
                *UiSpec.MenuName.ToString().Replace(TEXT(" "), TEXT("")));
            if (!QualifiedName.Equals(NodeWithCategory, ESearchCase::CaseSensitive))
            {
                continue;
            }

            const TSharedRef<FJsonObject> Match = MakeShared<FJsonObject>();
            Match->SetStringField(TEXT("palette_action"), QualifiedName);
            Match->SetStringField(TEXT("action_object"), ActionObject->GetPathName());
            Match->SetStringField(TEXT("action_object_class"), ActionObject->GetClass()->GetName());
            Match->SetStringField(TEXT("category"), UiSpec.Category.ToString());
            Match->SetStringField(TEXT("menu_name"), UiSpec.MenuName.ToString());
            Match->SetStringField(TEXT("tooltip"), UiSpec.Tooltip.ToString());
            Match->SetBoolField(TEXT("pin_probe_required"), true);
            MatchValues.Add(MakeShared<FJsonValueObject>(Match));
        }
    }

    const bool bOriginalGraphUnchanged = SourceGraph->Nodes.Num() == OriginalNodeCount;
    const bool bDirtyStateUnchanged = Blueprint->GetOutermost()->IsDirty() == bPackageDirtyBefore;
    Root->SetArrayField(TEXT("matches"), MatchValues);
    Root->SetNumberField(TEXT("match_count"), MatchValues.Num());
    Root->SetBoolField(TEXT("original_graph_unchanged"), bOriginalGraphUnchanged);
    Root->SetBoolField(TEXT("package_dirty_state_unchanged"), bDirtyStateUnchanged);
    Root->SetBoolField(
        TEXT("ok"),
        MatchValues.Num() > 0 && bOriginalGraphUnchanged && bDirtyStateUnchanged);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.describe_blueprint_node_action(blueprint, graph_name, palette_action)"));
    if (MatchValues.Num() == 0)
    {
        Root->SetStringField(TEXT("error"), TEXT("No exact filtered palette action matched."));
    }
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SearchBlueprintNodeActions(
    UBlueprint* Blueprint,
    FName GraphName,
    const FString& Query,
    int32 MaxResults)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("search_blueprint_node_actions"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("graph_name"), GraphName.ToString());
    Root->SetStringField(TEXT("query"), Query);

#if WITH_EDITOR
    if (!Blueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("Blueprint was null."));
        return AIStudioJsonString(Root);
    }
    const FString NormalizedQuery = Query.TrimStartAndEnd().ToLower();
    if (NormalizedQuery.IsEmpty())
    {
        Root->SetStringField(TEXT("error"), TEXT("A non-empty search query is required."));
        return AIStudioJsonString(Root);
    }
    MaxResults = FMath::Clamp(MaxResults, 1, 200);

    UEdGraph* SourceGraph = nullptr;
    TArray<UEdGraph*> Graphs;
    Graphs.Append(Blueprint->UbergraphPages);
    Graphs.Append(Blueprint->FunctionGraphs);
    Graphs.Append(Blueprint->MacroGraphs);
    Graphs.Append(Blueprint->DelegateSignatureGraphs);
    for (UEdGraph* Graph : Graphs)
    {
        if (Graph && Graph->GetFName() == GraphName)
        {
            SourceGraph = Graph;
            break;
        }
    }
    if (!SourceGraph)
    {
        Root->SetStringField(TEXT("error"), TEXT("The requested graph was not found."));
        return AIStudioJsonString(Root);
    }

    const int32 OriginalNodeCount = SourceGraph->Nodes.Num();
    const bool bPackageDirtyBefore = Blueprint->GetOutermost()->IsDirty();
    FBlueprintActionFilter Filter;
    FBlueprintActionContext& FilterContext = Filter.Context;
    FilterContext.Graphs.Add(SourceGraph);
    FilterContext.Blueprints.Add(Blueprint);

    struct FSearchMatch
    {
        int32 Score = 0;
        FString QualifiedName;
        FString Category;
        FString MenuName;
        FString Tooltip;
        FString ActionObject;
        FString ActionObjectClass;
    };
    TArray<FSearchMatch> Matches;
    TSet<FString> Seen;
    const FBlueprintActionDatabase::FActionRegistry& Registry =
        FBlueprintActionDatabase::Get().GetAllActions();
    for (auto Iterator(Registry.CreateConstIterator()); Iterator; ++Iterator)
    {
        UObject* ActionObject = Iterator->Key.ResolveObjectPtr();
        if (!ActionObject)
        {
            continue;
        }
        for (const UBlueprintNodeSpawner* Spawner : Iterator->Value)
        {
            if (!Spawner)
            {
                continue;
            }
            FBlueprintActionInfo ActionInfo(ActionObject, Spawner);
            if (Filter.IsFiltered(ActionInfo))
            {
                continue;
            }
            const FBlueprintActionUiSpec UiSpec = Spawner->GetUiSpec(
                FilterContext,
                ActionInfo.GetBindings());
            const FString Category = UiSpec.Category.ToString();
            const FString MenuName = UiSpec.MenuName.ToString();
            const FString QualifiedName = FString::Printf(
                TEXT("%s|%s"),
                *Category.Replace(TEXT(" "), TEXT("")),
                *MenuName.Replace(TEXT(" "), TEXT("")));
            const FString SearchText = FString::Printf(
                TEXT("%s %s %s %s"),
                *Category,
                *MenuName,
                *UiSpec.Tooltip.ToString(),
                *ActionObject->GetPathName()).ToLower();
            if (!SearchText.Contains(NormalizedQuery) || Seen.Contains(QualifiedName))
            {
                continue;
            }
            Seen.Add(QualifiedName);
            FSearchMatch Match;
            Match.QualifiedName = QualifiedName;
            Match.Category = Category;
            Match.MenuName = MenuName;
            Match.Tooltip = UiSpec.Tooltip.ToString();
            Match.ActionObject = ActionObject->GetPathName();
            Match.ActionObjectClass = ActionObject->GetClass()->GetName();
            const FString NormalizedMenu = MenuName.ToLower();
            Match.Score = NormalizedMenu.Equals(NormalizedQuery) ? 300
                : NormalizedMenu.StartsWith(NormalizedQuery) ? 200
                : NormalizedMenu.Contains(NormalizedQuery) ? 100
                : 10;
            Matches.Add(MoveTemp(Match));
        }
    }
    Matches.Sort([](const FSearchMatch& A, const FSearchMatch& B)
    {
        if (A.Score != B.Score)
        {
            return A.Score > B.Score;
        }
        return A.QualifiedName < B.QualifiedName;
    });

    TArray<TSharedPtr<FJsonValue>> MatchValues;
    for (int32 Index = 0; Index < FMath::Min(MaxResults, Matches.Num()); ++Index)
    {
        const FSearchMatch& Match = Matches[Index];
        const TSharedRef<FJsonObject> Object = MakeShared<FJsonObject>();
        Object->SetNumberField(TEXT("score"), Match.Score);
        Object->SetStringField(TEXT("palette_action"), Match.QualifiedName);
        Object->SetStringField(TEXT("category"), Match.Category);
        Object->SetStringField(TEXT("menu_name"), Match.MenuName);
        Object->SetStringField(TEXT("tooltip"), Match.Tooltip);
        Object->SetStringField(TEXT("action_object"), Match.ActionObject);
        Object->SetStringField(TEXT("action_object_class"), Match.ActionObjectClass);
        MatchValues.Add(MakeShared<FJsonValueObject>(Object));
    }
    const bool bOriginalGraphUnchanged = SourceGraph->Nodes.Num() == OriginalNodeCount;
    const bool bDirtyStateUnchanged = Blueprint->GetOutermost()->IsDirty() == bPackageDirtyBefore;
    Root->SetArrayField(TEXT("matches"), MatchValues);
    Root->SetNumberField(TEXT("total_match_count"), Matches.Num());
    Root->SetNumberField(TEXT("returned_match_count"), MatchValues.Num());
    Root->SetBoolField(TEXT("original_graph_unchanged"), bOriginalGraphUnchanged);
    Root->SetBoolField(TEXT("package_dirty_state_unchanged"), bDirtyStateUnchanged);
    Root->SetBoolField(TEXT("ok"), bOriginalGraphUnchanged && bDirtyStateUnchanged);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.search_blueprint_node_actions(blueprint, graph_name, query, max_results)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::ConfigureBlueprintReplication(
    UBlueprint* Blueprint,
    const TArray<FName>& ReplicatedVariables,
    const TArray<FName>& RepNotifyVariables,
    const TArray<FName>& ServerRpcFunctions,
    bool bReliable,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("configure_blueprint_replication"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    if (!Blueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("Blueprint was null."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(
        NSLOCTEXT("AIStudioBridge", "ConfigureBlueprintReplication", "Configure Blueprint Replication"));
    Blueprint->Modify();
    TArray<TSharedPtr<FJsonValue>> VariableRows;
    TArray<TSharedPtr<FJsonValue>> FunctionRows;
    TArray<FString> Errors;

    auto ConfigureVariable = [&](FName VariableName, bool bRepNotify)
    {
        const int32 VariableIndex = FBlueprintEditorUtils::FindNewVariableIndex(Blueprint, VariableName);
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("name"), VariableName.ToString());
        Row->SetBoolField(TEXT("rep_notify"), bRepNotify);
        if (VariableIndex == INDEX_NONE)
        {
            Row->SetBoolField(TEXT("ok"), false);
            Row->SetStringField(TEXT("error"), TEXT("Member variable was not found."));
            Errors.Add(FString::Printf(TEXT("Variable not found: %s"), *VariableName.ToString()));
        }
        else
        {
            FBPVariableDescription& Variable = Blueprint->NewVariables[VariableIndex];
            Variable.PropertyFlags |= CPF_Net;
            if (bRepNotify)
            {
                const FName NotifyName(*FString::Printf(TEXT("OnRep_%s"), *VariableName.ToString()));
                UEdGraph* NotifyGraph = nullptr;
                for (UEdGraph* Graph : Blueprint->FunctionGraphs)
                {
                    if (Graph && Graph->GetFName() == NotifyName)
                    {
                        NotifyGraph = Graph;
                        break;
                    }
                }
                if (!NotifyGraph)
                {
                    NotifyGraph = FBlueprintEditorUtils::CreateNewGraph(
                        Blueprint,
                        NotifyName,
                        UEdGraph::StaticClass(),
                        UEdGraphSchema_K2::StaticClass());
                    FBlueprintEditorUtils::AddFunctionGraph<UFunction>(
                        Blueprint,
                        NotifyGraph,
                        true,
                        nullptr);
                }
                Variable.PropertyFlags |= CPF_RepNotify;
                FBlueprintEditorUtils::SetBlueprintVariableRepNotifyFunc(
                    Blueprint,
                    VariableName,
                    NotifyName);
                Row->SetStringField(TEXT("rep_notify_function"), NotifyName.ToString());
            }
            Row->SetBoolField(TEXT("ok"), true);
            Row->SetBoolField(TEXT("replicated"), (Variable.PropertyFlags & CPF_Net) != 0);
        }
        VariableRows.Add(MakeShared<FJsonValueObject>(Row));
    };

    TSet<FName> RepNotifySet;
    TSet<FName> AllVariables;
    for (const FName VariableName : RepNotifyVariables)
    {
        RepNotifySet.Add(VariableName);
    }
    for (const FName VariableName : ReplicatedVariables)
    {
        AllVariables.Add(VariableName);
    }
    AllVariables.Append(RepNotifySet);
    for (const FName VariableName : AllVariables)
    {
        ConfigureVariable(VariableName, RepNotifySet.Contains(VariableName));
    }

    for (const FName FunctionName : ServerRpcFunctions)
    {
        UEdGraph* FunctionGraph = nullptr;
        for (UEdGraph* Graph : Blueprint->FunctionGraphs)
        {
            if (Graph && Graph->GetFName() == FunctionName)
            {
                FunctionGraph = Graph;
                break;
            }
        }
        if (!FunctionGraph)
        {
            FunctionGraph = FBlueprintEditorUtils::CreateNewGraph(
                Blueprint,
                FunctionName,
                UEdGraph::StaticClass(),
                UEdGraphSchema_K2::StaticClass());
            FBlueprintEditorUtils::AddFunctionGraph<UFunction>(
                Blueprint,
                FunctionGraph,
                true,
                nullptr);
        }

        TArray<UK2Node_FunctionEntry*> Entries;
        FunctionGraph->GetNodesOfClass(Entries);
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("name"), FunctionName.ToString());
        if (Entries.Num() == 0 || !Entries[0])
        {
            Row->SetBoolField(TEXT("ok"), false);
            Row->SetStringField(TEXT("error"), TEXT("Function entry node was unavailable."));
            Errors.Add(FString::Printf(TEXT("Function entry unavailable: %s"), *FunctionName.ToString()));
        }
        else
        {
            UK2Node_FunctionEntry* Entry = Entries[0];
            int32 Flags = Entry->GetExtraFlags();
            Flags &= ~(FUNC_NetMulticast | FUNC_NetClient);
            Flags |= FUNC_Net | FUNC_NetServer;
            if (bReliable)
            {
                Flags |= FUNC_NetReliable;
            }
            else
            {
                Flags &= ~FUNC_NetReliable;
            }
            Entry->SetExtraFlags(Flags);
            Row->SetBoolField(TEXT("ok"), true);
            Row->SetBoolField(TEXT("server"), (Flags & FUNC_NetServer) != 0);
            Row->SetBoolField(TEXT("reliable"), (Flags & FUNC_NetReliable) != 0);
            Row->SetNumberField(TEXT("function_flags"), Flags);
        }
        FunctionRows.Add(MakeShared<FJsonValueObject>(Row));
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    FKismetEditorUtilities::CompileBlueprint(Blueprint);
    if (AActor* DefaultActor = Cast<AActor>(
        Blueprint->GeneratedClass ? Blueprint->GeneratedClass->GetDefaultObject() : nullptr))
    {
        DefaultActor->SetReplicates(true);
    }
    if (bSave)
    {
        AIStudioSaveAssetPackage(Blueprint);
    }

    Root->SetArrayField(TEXT("variables"), VariableRows);
    Root->SetArrayField(TEXT("server_rpc_functions"), FunctionRows);
    TArray<TSharedPtr<FJsonValue>> ErrorValues;
    for (const FString& Error : Errors)
    {
        ErrorValues.Add(MakeShared<FJsonValueString>(Error));
    }
    Root->SetArrayField(TEXT("errors"), ErrorValues);
    Root->SetBoolField(TEXT("actor_replicates"), true);
    Root->SetBoolField(TEXT("saved"), bSave);
    Root->SetBoolField(TEXT("ok"), Errors.Num() == 0);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.configure_blueprint_replication(blueprint, replicated_variables, rep_notify_variables, server_rpc_functions, reliable, save)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::EnsureBlueprintFunction(
    UBlueprint* Blueprint,
    FName FunctionName,
    const FString& InputsJson,
    const FString& OutputsJson,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.ensure_blueprint_function(blueprint, function_name, inputs_json, outputs_json, save)"));
    Root->SetStringField(TEXT("capability"), TEXT("ensure_blueprint_function"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("function_name"), FunctionName.ToString());

#if WITH_EDITOR
    if (!Blueprint || FunctionName.IsNone())
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_arguments"));
        return AIStudioJsonString(Root);
    }

    UEdGraph* FunctionGraph = nullptr;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        if (Graph && Graph->GetFName() == FunctionName)
        {
            FunctionGraph = Graph;
            break;
        }
    }
    const bool bCreated = FunctionGraph == nullptr;
    if (!FunctionGraph)
    {
        FunctionGraph = FBlueprintEditorUtils::CreateNewGraph(
            Blueprint,
            FunctionName,
            UEdGraph::StaticClass(),
            UEdGraphSchema_K2::StaticClass());
        FBlueprintEditorUtils::AddFunctionGraph<UFunction>(
            Blueprint,
            FunctionGraph,
            true,
            nullptr);
    }
    if (!FunctionGraph)
    {
        Root->SetStringField(TEXT("status"), TEXT("function_graph_create_failed"));
        return AIStudioJsonString(Root);
    }

    UK2Node_FunctionEntry* Entry = nullptr;
    UK2Node_FunctionResult* Result = nullptr;
    for (UEdGraphNode* Node : FunctionGraph->Nodes)
    {
        Entry = Entry ? Entry : Cast<UK2Node_FunctionEntry>(Node);
        Result = Result ? Result : Cast<UK2Node_FunctionResult>(Node);
    }
    if (!Entry)
    {
        Root->SetStringField(TEXT("status"), TEXT("function_entry_not_found"));
        return AIStudioJsonString(Root);
    }

    auto ParseRows = [](const FString& JsonText, TArray<TSharedPtr<FJsonValue>>& Rows) -> bool
    {
        if (JsonText.TrimStartAndEnd().IsEmpty())
        {
            return true;
        }
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
        return FJsonSerializer::Deserialize(Reader, Rows);
    };
    auto PinTypeFromRow = [](const TSharedPtr<FJsonObject>& Row) -> FEdGraphPinType
    {
        FEdGraphPinType PinType;
        const FString Type = Row->GetStringField(TEXT("type")).ToLower();
        if (Type == TEXT("bool") || Type == TEXT("boolean"))
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_Boolean;
        }
        else if (Type == TEXT("int") || Type == TEXT("integer"))
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_Int;
        }
        else if (Type == TEXT("int64"))
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_Int64;
        }
        else if (Type == TEXT("float"))
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_Float;
        }
        else if (Type == TEXT("double") || Type == TEXT("number"))
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_Double;
        }
        else if (Type == TEXT("name"))
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_Name;
        }
        else
        {
            PinType.PinCategory = UEdGraphSchema_K2::PC_String;
        }
        bool bIsArray = false;
        Row->TryGetBoolField(TEXT("is_array"), bIsArray);
        PinType.ContainerType = bIsArray ? EPinContainerType::Array : EPinContainerType::None;
        return PinType;
    };
    auto EnsurePins = [&PinTypeFromRow](
        UK2Node_EditablePinBase* Node,
        const TArray<TSharedPtr<FJsonValue>>& Rows,
        EEdGraphPinDirection Direction,
        TArray<TSharedPtr<FJsonValue>>& Added) -> bool
    {
        if (!Node && !Rows.IsEmpty())
        {
            return false;
        }
        for (const TSharedPtr<FJsonValue>& Value : Rows)
        {
            const TSharedPtr<FJsonObject> Row = Value ? Value->AsObject() : nullptr;
            if (!Row || !Row->HasTypedField<EJson::String>(TEXT("name"))
                || !Row->HasTypedField<EJson::String>(TEXT("type")))
            {
                return false;
            }
            const FName PinName(*Row->GetStringField(TEXT("name")));
            UEdGraphPin* Existing = Node->FindPin(PinName);
            if (!Existing)
            {
                Existing = Node->CreateUserDefinedPin(
                    PinName,
                    PinTypeFromRow(Row),
                    Direction,
                    false);
                if (Existing)
                {
                    Added.Add(MakeShared<FJsonValueString>(PinName.ToString()));
                }
            }
            if (!Existing)
            {
                return false;
            }
        }
        return true;
    };

    TArray<TSharedPtr<FJsonValue>> InputRows;
    TArray<TSharedPtr<FJsonValue>> OutputRows;
    if (!ParseRows(InputsJson, InputRows) || !ParseRows(OutputsJson, OutputRows))
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_pin_json"));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> AddedInputs;
    TArray<TSharedPtr<FJsonValue>> AddedOutputs;
    const bool bInputsOk = EnsurePins(Entry, InputRows, EGPD_Output, AddedInputs);
    const bool bOutputsOk = EnsurePins(Result, OutputRows, EGPD_Input, AddedOutputs);
    if (!bInputsOk || !bOutputsOk)
    {
        Root->SetStringField(TEXT("status"), TEXT("pin_authoring_failed"));
        return AIStudioJsonString(Root);
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    FKismetEditorUtilities::CompileBlueprint(Blueprint);
    const bool bSaved = !bSave || AIStudioSaveAssetPackage(Blueprint);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(
        TEXT("status"),
        bSaved ? (bCreated ? TEXT("created") : TEXT("updated")) : TEXT("save_failed"));
    Root->SetStringField(TEXT("blueprint_path"), Blueprint->GetPathName());
    Root->SetArrayField(TEXT("added_inputs"), AddedInputs);
    Root->SetArrayField(TEXT("added_outputs"), AddedOutputs);
    Root->SetBoolField(TEXT("saved"), bSaved);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RenameBlueprintSymbol(
    UBlueprint* Blueprint,
    FName OldName,
    FName NewName,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.rename_blueprint_symbol(blueprint, old_name, new_name, save)"));
    Root->SetStringField(TEXT("capability"), TEXT("rename_blueprint_symbol"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("old_name"), OldName.ToString());
    Root->SetStringField(TEXT("new_name"), NewName.ToString());

#if WITH_EDITOR
    if (!Blueprint || OldName.IsNone() || NewName.IsNone() || OldName == NewName)
    {
        Root->SetStringField(TEXT("status"), TEXT("invalid_arguments"));
        return AIStudioJsonString(Root);
    }
    bool bVariableRenamed = false;
    for (const FBPVariableDescription& Variable : Blueprint->NewVariables)
    {
        if (Variable.VarName == OldName)
        {
            FBlueprintEditorUtils::RenameMemberVariable(Blueprint, OldName, NewName);
            bVariableRenamed = true;
            break;
        }
    }

    bool bGraphRenamed = false;
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        if (Graph && Graph->GetFName() == OldName)
        {
            FBlueprintEditorUtils::RenameGraph(Graph, NewName.ToString());
            bGraphRenamed = true;
            break;
        }
    }
    const bool bChanged = bVariableRenamed || bGraphRenamed;
    if (bChanged)
    {
        FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
        FKismetEditorUtilities::CompileBlueprint(Blueprint);
    }
    const bool bSaved = !bChanged || !bSave || AIStudioSaveAssetPackage(Blueprint);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(
        TEXT("status"),
        !bChanged ? TEXT("symbol_not_found") : bSaved ? TEXT("renamed") : TEXT("save_failed"));
    Root->SetStringField(TEXT("blueprint_path"), Blueprint->GetPathName());
    Root->SetBoolField(TEXT("changed"), bChanged);
    Root->SetBoolField(TEXT("variable_renamed"), bVariableRenamed);
    Root->SetBoolField(TEXT("function_graph_renamed"), bGraphRenamed);
    Root->SetBoolField(TEXT("saved"), bSaved);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::BindNiagaraUserParametersOnBeginPlay(
    UBlueprint* Blueprint,
    const TArray<FName>& ComponentNames,
    const FString& BindingsJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("bind_niagara_user_parameters_on_begin_play"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    if (!Blueprint || Blueprint->UbergraphPages.Num() == 0 || !Blueprint->UbergraphPages[0])
    {
        Root->SetStringField(TEXT("error"), TEXT("Blueprint or EventGraph was unavailable."));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> BindingValues;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(BindingsJson);
    if (!FJsonSerializer::Deserialize(Reader, BindingValues))
    {
        Root->SetStringField(TEXT("error"), TEXT("BindingsJson must be a JSON array."));
        return AIStudioJsonString(Root);
    }

    UEdGraph* Graph = Blueprint->UbergraphPages[0];
    const UEdGraphSchema_K2* K2Schema = GetDefault<UEdGraphSchema_K2>();
    UK2Node_Event* BeginPlay = nullptr;
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        UK2Node_Event* EventNode = Cast<UK2Node_Event>(Node);
        if (EventNode && EventNode->EventReference.GetMemberName() == FName(TEXT("ReceiveBeginPlay")))
        {
            BeginPlay = EventNode;
            break;
        }
    }
    if (!BeginPlay)
    {
        BeginPlay = NewObject<UK2Node_Event>(Graph);
        Graph->Modify();
        Graph->AddNode(BeginPlay, true, false);
        BeginPlay->CreateNewGuid();
        BeginPlay->EventReference.SetExternalMember(FName(TEXT("ReceiveBeginPlay")), AActor::StaticClass());
        BeginPlay->PostPlacedNewNode();
        BeginPlay->AllocateDefaultPins();
        BeginPlay->NodePosX = 0;
        BeginPlay->NodePosY = -120;
    }

    UK2Node_ExecutionSequence* Sequence = nullptr;
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (Node && Node->GetName().StartsWith(TEXT("AIStudio_FXBind_Sequence")))
        {
            Sequence = Cast<UK2Node_ExecutionSequence>(Node);
            break;
        }
    }
    const bool bCreatedSequence = Sequence == nullptr;
    if (!Sequence)
    {
        Sequence = NewObject<UK2Node_ExecutionSequence>(Graph);
        Graph->Modify();
        Graph->AddNode(Sequence, true, false);
        Sequence->CreateNewGuid();
        Sequence->PostPlacedNewNode();
        Sequence->AllocateDefaultPins();
        Sequence->Rename(TEXT("AIStudio_FXBind_Sequence"));
        Sequence->NodePosX = 280;
        Sequence->NodePosY = -60;
    }

    UEdGraphPin* BeginThen = BeginPlay->FindPin(UEdGraphSchema_K2::PN_Then);
    UEdGraphPin* SequenceExec = Sequence->GetExecPin();
    UEdGraphPin* Then0 = Sequence->FindPin(TEXT("then_0"));
    UEdGraphPin* ChainExec = Sequence->FindPin(TEXT("then_1"));
    if (bCreatedSequence && BeginThen && SequenceExec)
    {
        TArray<UEdGraphPin*> PreviousLinks = BeginThen->LinkedTo;
        BeginThen->BreakAllPinLinks();
        K2Schema->TryCreateConnection(BeginThen, SequenceExec);
        for (UEdGraphPin* Previous : PreviousLinks)
        {
            if (Previous && Then0)
            {
                K2Schema->TryCreateConnection(Then0, Previous);
            }
        }
    }

    TArray<TSharedPtr<FJsonValue>> Created;
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node || !Node->GetName().StartsWith(TEXT("AIStudio_FXBind_")) || Node == Sequence)
        {
            continue;
        }
        if (UEdGraphPin* ThenPin = Node->FindPin(UEdGraphSchema_K2::PN_Then))
        {
            if (ThenPin->LinkedTo.Num() == 0)
            {
                ChainExec = ThenPin;
            }
        }
    }
    int32 NodeY = 140;
    for (const FName& ComponentName : ComponentNames)
    {
        UK2Node_VariableGet* ComponentGet = AIStudioCreateVariableGetNode(Graph, ComponentName, 520, NodeY);
        UEdGraphPin* ComponentPin = AIStudioFindFirstOutputPin(ComponentGet);
        for (const TSharedPtr<FJsonValue>& Value : BindingValues)
        {
            const TSharedPtr<FJsonObject> Binding = Value.IsValid() ? Value->AsObject() : nullptr;
            if (!Binding.IsValid())
            {
                continue;
            }
            const FString VariableName = Binding->GetStringField(TEXT("variable_name"));
            const FString VariableType = Binding->GetStringField(TEXT("variable_type")).ToLower();
            const FString ParameterName = Binding->GetStringField(TEXT("parameter_name"));
            FName FunctionName = NAME_None;
            if (VariableType == TEXT("real") || VariableType == TEXT("float") || VariableType == TEXT("double"))
            {
                FunctionName = FName(TEXT("SetNiagaraVariableFloat"));
            }
            else if (VariableType == TEXT("bool") || VariableType == TEXT("boolean"))
            {
                FunctionName = FName(TEXT("SetNiagaraVariableBool"));
            }
            else if (VariableType == TEXT("linearcolor") || VariableType == TEXT("linear_color") || VariableType == TEXT("color"))
            {
                FunctionName = FName(TEXT("SetNiagaraVariableLinearColor"));
            }
            else if (VariableType == TEXT("vector") || VariableType == TEXT("vec3"))
            {
                FunctionName = FName(TEXT("SetNiagaraVariableVec3"));
            }
            const UFunction* Function = FunctionName.IsNone() ? nullptr : UNiagaraComponent::StaticClass()->FindFunctionByName(FunctionName);
            if (!Function)
            {
                continue;
            }
            const FString SetterNodeName = FString::Printf(TEXT("AIStudio_FXBind_%s_%s"), *ComponentName.ToString(), *VariableName);
            bool bAlreadyExists = false;
            for (UEdGraphNode* Node : Graph->Nodes)
            {
                if (Node && Node->GetName() == SetterNodeName)
                {
                    bAlreadyExists = true;
                    break;
                }
            }
            if (bAlreadyExists)
            {
                const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("component_name"), ComponentName.ToString());
                Row->SetStringField(TEXT("variable_name"), VariableName);
                Row->SetStringField(TEXT("parameter_name"), ParameterName);
                Row->SetStringField(TEXT("function"), FunctionName.ToString());
                Row->SetBoolField(TEXT("already_exists"), true);
                Row->SetBoolField(TEXT("exec_connected"), true);
                Row->SetBoolField(TEXT("self_connected"), true);
                Row->SetBoolField(TEXT("value_connected"), true);
                Created.Add(MakeShared<FJsonValueObject>(Row));
                continue;
            }
            UK2Node_VariableGet* VariableGet = AIStudioCreateVariableGetNode(Graph, FName(*VariableName), 840, NodeY);
            UK2Node_CallFunction* Setter = NewObject<UK2Node_CallFunction>(Graph);
            Graph->Modify();
            Graph->AddNode(Setter, true, false);
            Setter->CreateNewGuid();
            Setter->PostPlacedNewNode();
            Setter->SetFromFunction(Function);
            Setter->NodePosX = 1180;
            Setter->NodePosY = NodeY;
            Setter->AllocateDefaultPins();
            Setter->Rename(*SetterNodeName);

            UEdGraphPin* ExecutePin = Setter->FindPin(UEdGraphSchema_K2::PN_Execute);
            UEdGraphPin* ThenPin = Setter->FindPin(UEdGraphSchema_K2::PN_Then);
            UEdGraphPin* SelfPin = Setter->FindPin(UEdGraphSchema_K2::PN_Self);
            UEdGraphPin* NamePin = Setter->FindPin(TEXT("InVariableName"));
            UEdGraphPin* ValuePin = Setter->FindPin(TEXT("InValue"));
            UEdGraphPin* VariablePin = AIStudioFindFirstOutputPin(VariableGet);
            const bool bExec = ChainExec && ExecutePin && K2Schema->TryCreateConnection(ChainExec, ExecutePin);
            const bool bSelf = ComponentPin && SelfPin && K2Schema->TryCreateConnection(ComponentPin, SelfPin);
            const bool bValue = VariablePin && ValuePin && K2Schema->TryCreateConnection(VariablePin, ValuePin);
            if (NamePin)
            {
                NamePin->DefaultValue = ParameterName;
            }
            if (ThenPin)
            {
                ChainExec = ThenPin;
            }
            const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("component_name"), ComponentName.ToString());
            Row->SetStringField(TEXT("variable_name"), VariableName);
            Row->SetStringField(TEXT("parameter_name"), ParameterName);
            Row->SetStringField(TEXT("function"), FunctionName.ToString());
            Row->SetBoolField(TEXT("exec_connected"), bExec);
            Row->SetBoolField(TEXT("self_connected"), bSelf);
            Row->SetBoolField(TEXT("value_connected"), bValue);
            Created.Add(MakeShared<FJsonValueObject>(Row));
            NodeY += 96;
        }
        NodeY += 160;
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    FKismetEditorUtilities::CompileBlueprint(Blueprint);
    AIStudioSaveAssetPackage(Blueprint);
    Root->SetArrayField(TEXT("bindings_created"), Created);
    Root->SetNumberField(TEXT("binding_count"), Created.Num());
    Root->SetBoolField(TEXT("ok"), Created.Num() > 0);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.bind_niagara_user_parameters_on_begin_play(blueprint, component_names, bindings_json)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CreatePoseSearchSchema(
    const FString& SkeletonPath,
    const FString& AssetPath,
    int32 SampleRate)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_pose_search_schema"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_pose_search_schema(skeleton_path, asset_path, sample_rate)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    USkeleton* Skeleton = Cast<USkeleton>(AIStudioLoadAssetObject(SkeletonPath));
    if (!Skeleton || AssetPath.IsEmpty())
    {
        Root->SetStringField(TEXT("status"), Skeleton ? TEXT("invalid_asset_path") : TEXT("skeleton_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UPoseSearchSchema* Schema = Package
        ? NewObject<UPoseSearchSchema>(Package, FName(*AIStudioAssetNameFromAssetPath(AssetPath)), RF_Public | RF_Standalone | RF_Transactional)
        : nullptr;
    if (!Schema)
    {
        Root->SetStringField(TEXT("status"), TEXT("asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    Schema->Modify();
    Schema->SampleRate = FMath::Clamp(SampleRate, 1, 240);
    Schema->AddSkeleton(Skeleton);
    Schema->PostEditChange();
    FAssetRegistryModule::AssetCreated(Schema);
    const bool bSaved = AIStudioSaveAssetPackage(Schema);
    Root->SetBoolField(TEXT("ok"), bSaved && Schema->GetRoledSkeletons().Num() == 1);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("created_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), Schema->GetPathName());
    Root->SetNumberField(TEXT("sample_rate"), Schema->SampleRate);
    Root->SetNumberField(TEXT("skeleton_count"), Schema->GetRoledSkeletons().Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPoseSearchSchemaChannel(
    const FString& SchemaPath,
    const FString& ChannelClassPath,
    const FString& SettingsJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_pose_search_schema_channel"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_pose_search_schema_channel(schema_path, channel_class_path, settings_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchSchema* Schema = Cast<UPoseSearchSchema>(AIStudioLoadAssetObject(SchemaPath));
    UClass* ChannelClass = LoadClass<UPoseSearchFeatureChannel>(nullptr, *ChannelClassPath);
    if (!Schema || !ChannelClass || !ChannelClass->IsChildOf(UPoseSearchFeatureChannel::StaticClass()))
    {
        Root->SetStringField(TEXT("status"), Schema ? TEXT("channel_class_not_found") : TEXT("schema_not_found"));
        return AIStudioJsonString(Root);
    }
    UPoseSearchFeatureChannel* Channel = NewObject<UPoseSearchFeatureChannel>(Schema, ChannelClass, NAME_None, RF_Transactional);
    TArray<FString> Errors;
    TSharedPtr<FJsonObject> Settings = AIStudioParseJsonObject(SettingsJson.IsEmpty() ? TEXT("{}") : SettingsJson);
    Schema->Modify();
    Channel->Modify();
    const bool bApplied = Settings.IsValid() && AIStudioSetPropertiesFromJson(Channel, Settings, Errors);
    Schema->AddChannel(Channel);
    Schema->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(Schema);
    Root->SetBoolField(TEXT("ok"), bSaved && bApplied && Errors.IsEmpty());
    Root->SetStringField(TEXT("status"), bSaved ? (Errors.IsEmpty() ? TEXT("channel_added_and_saved") : TEXT("property_errors")) : TEXT("save_failed"));
    Root->SetStringField(TEXT("channel_class"), Channel->GetClass()->GetPathName());
    Root->SetNumberField(TEXT("channel_count"), Schema->GetChannels().Num());
    TArray<TSharedPtr<FJsonValue>> ErrorValues;
    for (const FString& Error : Errors)
    {
        ErrorValues.Add(MakeShared<FJsonValueString>(Error));
    }
    Root->SetArrayField(TEXT("property_errors"), ErrorValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CreatePoseSearchDatabase(const FString& SchemaPath, const FString& AssetPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_pose_search_database"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_pose_search_database(schema_path, asset_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchSchema* Schema = Cast<UPoseSearchSchema>(AIStudioLoadAssetObject(SchemaPath));
    if (!Schema || AssetPath.IsEmpty())
    {
        Root->SetStringField(TEXT("status"), Schema ? TEXT("invalid_asset_path") : TEXT("schema_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UPoseSearchDatabase* Database = Package
        ? NewObject<UPoseSearchDatabase>(Package, FName(*AIStudioAssetNameFromAssetPath(AssetPath)), RF_Public | RF_Standalone | RF_Transactional)
        : nullptr;
    if (!Database)
    {
        Root->SetStringField(TEXT("status"), TEXT("asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    Database->Modify();
    Database->Schema = Schema;
    Database->PostEditChange();
    FAssetRegistryModule::AssetCreated(Database);
    const bool bSaved = AIStudioSaveAssetPackage(Database);
    Root->SetBoolField(TEXT("ok"), bSaved && Database->Schema == Schema);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("created_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), Database->GetPathName());
    Root->SetStringField(TEXT("schema_path"), Schema->GetPathName());
    Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPoseSearchAnimation(const FString& DatabasePath, const FString& AnimationPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_pose_search_animation"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_pose_search_animation(database_path, animation_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchDatabase* Database = Cast<UPoseSearchDatabase>(AIStudioLoadAssetObject(DatabasePath));
    UObject* Animation = AIStudioLoadAssetObject(AnimationPath);
    if (!Database || !Animation)
    {
        Root->SetStringField(TEXT("status"), Database ? TEXT("animation_not_found") : TEXT("database_not_found"));
        return AIStudioJsonString(Root);
    }
    for (int32 Index = 0; Index < Database->GetNumAnimationAssets(); ++Index)
    {
        if (Database->GetAnimationAsset(Index) == Animation)
        {
            Root->SetBoolField(TEXT("ok"), true);
            Root->SetStringField(TEXT("status"), TEXT("already_present"));
            Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
            return AIStudioJsonString(Root);
        }
    }
    Database->Modify();
    FPoseSearchDatabaseAnimationAsset Entry;
    Entry.AnimAsset = Animation;
    Database->AddAnimationAsset(Entry);
    Database->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(Database);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("animation_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemovePoseSearchAnimation(const FString& DatabasePath, const FString& AnimationPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_pose_search_animation"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_pose_search_animation(database_path, animation_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchDatabase* Database = Cast<UPoseSearchDatabase>(AIStudioLoadAssetObject(DatabasePath));
    UObject* Animation = AIStudioLoadAssetObject(AnimationPath);
    if (!Database || !Animation)
    {
        Root->SetStringField(TEXT("status"), Database ? TEXT("animation_not_found") : TEXT("database_not_found"));
        return AIStudioJsonString(Root);
    }
    int32 FoundIndex = INDEX_NONE;
    for (int32 Index = 0; Index < Database->GetNumAnimationAssets(); ++Index)
    {
        if (Database->GetAnimationAsset(Index) == Animation)
        {
            FoundIndex = Index;
            break;
        }
    }
    if (FoundIndex == INDEX_NONE)
    {
        Root->SetStringField(TEXT("status"), TEXT("animation_not_present"));
        return AIStudioJsonString(Root);
    }
    Database->Modify();
    Database->RemoveAnimationAssetAt(FoundIndex);
    Database->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(Database);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("animation_removed_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CreatePhysicsAsset(
    const FString& SkeletalMeshPath,
    const FString& AssetPath,
    bool bAssignToMesh)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_physics_asset"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_physics_asset(skeletal_mesh_path, asset_path, assign_to_mesh)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    USkeletalMesh* Mesh = Cast<USkeletalMesh>(AIStudioLoadAssetObject(SkeletalMeshPath));
    if (!Mesh || AssetPath.IsEmpty())
    {
        Root->SetStringField(TEXT("status"), Mesh ? TEXT("invalid_asset_path") : TEXT("skeletal_mesh_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UPhysicsAsset* PhysicsAsset = Package
        ? Cast<UPhysicsAsset>(UPhysicsAssetFactory::CreatePhysicsAssetFromMesh(
            FName(*AIStudioAssetNameFromAssetPath(AssetPath)), Package, Mesh, bAssignToMesh))
        : nullptr;
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    FAssetRegistryModule::AssetCreated(PhysicsAsset);
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved && PhysicsAsset->SkeletalBodySetups.Num() > 0);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("created_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), PhysicsAsset->GetPathName());
    Root->SetNumberField(TEXT("body_count"), PhysicsAsset->SkeletalBodySetups.Num());
    Root->SetNumberField(TEXT("constraint_count"), PhysicsAsset->ConstraintSetup.Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPhysicsBody(
    const FString& PhysicsAssetPath,
    FName BoneName,
    const FString& ShapeType)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_physics_body"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_physics_body(physics_asset_path, bone_name, shape_type)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    if (USkeletalMesh* PreviewMesh = PhysicsAsset->GetPreviewMesh())
    {
        if (PreviewMesh->GetRefSkeleton().FindBoneIndex(BoneName) == INDEX_NONE)
        {
            Root->SetStringField(TEXT("status"), TEXT("bone_not_found_on_preview_mesh"));
            Root->SetStringField(TEXT("bone_name"), BoneName.ToString());
            Root->SetStringField(TEXT("preview_mesh"), PreviewMesh->GetPathName());
            return AIStudioJsonString(Root);
        }
    }
    if (PhysicsAsset->FindBodyIndex(BoneName) != INDEX_NONE)
    {
        Root->SetBoolField(TEXT("ok"), true);
        Root->SetStringField(TEXT("status"), TEXT("already_present"));
        return AIStudioJsonString(Root);
    }
    PhysicsAsset->Modify();
    FPhysAssetCreateParams Params;
    const int32 BodyIndex = FPhysicsAssetUtils::CreateNewBody(PhysicsAsset, BoneName, Params);
    USkeletalBodySetup* Body = PhysicsAsset->SkeletalBodySetups.IsValidIndex(BodyIndex)
        ? PhysicsAsset->SkeletalBodySetups[BodyIndex].Get()
        : nullptr;
    if (!Body)
    {
        Root->SetStringField(TEXT("status"), TEXT("body_create_failed"));
        return AIStudioJsonString(Root);
    }
    const FString Shape = ShapeType.ToLower();
    if (Shape == TEXT("sphere"))
    {
        FKSphereElem Elem;
        Elem.Radius = 15.0f;
        Body->AggGeom.SphereElems.Add(Elem);
    }
    else if (Shape == TEXT("box"))
    {
        FKBoxElem Elem;
        Elem.X = Elem.Y = Elem.Z = 30.0f;
        Body->AggGeom.BoxElems.Add(Elem);
    }
    else
    {
        FKSphylElem Elem;
        Elem.Radius = 15.0f;
        Elem.Length = 30.0f;
        Body->AggGeom.SphylElems.Add(Elem);
    }
    Body->InvalidatePhysicsData();
    Body->CreatePhysicsMeshes();
    PhysicsAsset->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("body_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("body_index"), BodyIndex);
    Root->SetStringField(TEXT("bone_name"), BoneName.ToString());
    Root->SetStringField(TEXT("shape_type"), Shape);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPhysicsConstraint(
    const FString& PhysicsAssetPath,
    FName BoneNameA,
    FName BoneNameB)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_physics_constraint"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_physics_constraint(physics_asset_path, bone_name_a, bone_name_b)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset || PhysicsAsset->FindBodyIndex(BoneNameA) == INDEX_NONE || PhysicsAsset->FindBodyIndex(BoneNameB) == INDEX_NONE)
    {
        Root->SetStringField(TEXT("status"), PhysicsAsset ? TEXT("body_not_found") : TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    for (int32 ExistingIndex = 0; ExistingIndex < PhysicsAsset->ConstraintSetup.Num(); ++ExistingIndex)
    {
        const UPhysicsConstraintTemplate* Existing = PhysicsAsset->ConstraintSetup[ExistingIndex];
        if (!Existing)
        {
            continue;
        }
        const FName ExistingA = Existing->DefaultInstance.ConstraintBone1;
        const FName ExistingB = Existing->DefaultInstance.ConstraintBone2;
        if ((ExistingA == BoneNameA && ExistingB == BoneNameB)
            || (ExistingA == BoneNameB && ExistingB == BoneNameA))
        {
            Root->SetBoolField(TEXT("ok"), true);
            Root->SetStringField(TEXT("status"), TEXT("already_present"));
            Root->SetNumberField(TEXT("constraint_index"), ExistingIndex);
            Root->SetStringField(TEXT("constraint_name"), Existing->GetName());
            return AIStudioJsonString(Root);
        }
    }
    PhysicsAsset->Modify();
    const FName ConstraintName(*FString::Printf(TEXT("%s_to_%s"), *BoneNameA.ToString(), *BoneNameB.ToString()));
    const int32 ConstraintIndex = FPhysicsAssetUtils::CreateNewConstraint(PhysicsAsset, ConstraintName);
    UPhysicsConstraintTemplate* Constraint = PhysicsAsset->ConstraintSetup.IsValidIndex(ConstraintIndex)
        ? PhysicsAsset->ConstraintSetup[ConstraintIndex]
        : nullptr;
    if (!Constraint)
    {
        Root->SetStringField(TEXT("status"), TEXT("constraint_create_failed"));
        return AIStudioJsonString(Root);
    }
    Constraint->DefaultInstance.ConstraintBone1 = BoneNameA;
    Constraint->DefaultInstance.ConstraintBone2 = BoneNameB;
    PhysicsAsset->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("constraint_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("constraint_index"), ConstraintIndex);
    Root->SetStringField(TEXT("constraint_name"), ConstraintName.ToString());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectPhysicsAsset(const FString& PhysicsAssetPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_physics_asset"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_physics_asset(physics_asset_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> Bodies;
    for (int32 Index = 0; Index < PhysicsAsset->SkeletalBodySetups.Num(); ++Index)
    {
        const USkeletalBodySetup* Body = PhysicsAsset->SkeletalBodySetups[Index].Get();
        if (!Body)
        {
            continue;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("index"), Index);
        Row->SetStringField(TEXT("name"), Body->GetName());
        Row->SetStringField(TEXT("bone_name"), Body->BoneName.ToString());
        Row->SetNumberField(TEXT("sphere_count"), Body->AggGeom.SphereElems.Num());
        Row->SetNumberField(TEXT("box_count"), Body->AggGeom.BoxElems.Num());
        Row->SetNumberField(TEXT("capsule_count"), Body->AggGeom.SphylElems.Num());
        Row->SetNumberField(TEXT("convex_count"), Body->AggGeom.ConvexElems.Num());
        Bodies.Add(MakeShared<FJsonValueObject>(Row));
    }
    TArray<TSharedPtr<FJsonValue>> Constraints;
    for (int32 Index = 0; Index < PhysicsAsset->ConstraintSetup.Num(); ++Index)
    {
        const UPhysicsConstraintTemplate* Constraint = PhysicsAsset->ConstraintSetup[Index];
        if (!Constraint)
        {
            continue;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("index"), Index);
        Row->SetStringField(TEXT("name"), Constraint->GetName());
        Row->SetStringField(TEXT("bone_name_a"), Constraint->DefaultInstance.ConstraintBone1.ToString());
        Row->SetStringField(TEXT("bone_name_b"), Constraint->DefaultInstance.ConstraintBone2.ToString());
        Row->SetNumberField(TEXT("profile_count"), Constraint->ProfileHandles.Num());
        Constraints.Add(MakeShared<FJsonValueObject>(Row));
    }
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("status"), TEXT("inspected"));
    Root->SetStringField(TEXT("asset_path"), PhysicsAsset->GetPathName());
    Root->SetNumberField(TEXT("body_count"), Bodies.Num());
    Root->SetNumberField(TEXT("constraint_count"), Constraints.Num());
    Root->SetArrayField(TEXT("bodies"), Bodies);
    Root->SetArrayField(TEXT("constraints"), Constraints);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetPhysicsBodyProperty(
    const FString& PhysicsAssetPath,
    FName BodyName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_physics_body_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_physics_body_property(physics_asset_path, body_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    USkeletalBodySetup* Body = nullptr;
    if (PhysicsAsset)
    {
        const int32 BodyIndex = PhysicsAsset->FindBodyIndex(BodyName);
        Body = PhysicsAsset->SkeletalBodySetups.IsValidIndex(BodyIndex)
            ? PhysicsAsset->SkeletalBodySetups[BodyIndex].Get()
            : nullptr;
        if (!Body)
        {
            const TObjectPtr<USkeletalBodySetup>* Match = PhysicsAsset->SkeletalBodySetups.FindByPredicate(
                [BodyName](const TObjectPtr<USkeletalBodySetup>& Candidate)
                {
                    return Candidate && Candidate->GetFName() == BodyName;
                });
            Body = Match ? Match->Get() : nullptr;
        }
    }
    void* PropertyContainer = Body;
    UStruct* PropertyOwnerStruct = Body ? Body->GetClass() : nullptr;
    FProperty* Property = Body ? AIStudioFindFlexibleProperty(PropertyOwnerStruct, PropertyName) : nullptr;
    FString PropertyScope = TEXT("body_setup");
    if (Body && !Property)
    {
        PropertyContainer = &Body->DefaultInstance;
        PropertyOwnerStruct = FBodyInstance::StaticStruct();
        Property = AIStudioFindFlexibleProperty(PropertyOwnerStruct, PropertyName);
        PropertyScope = TEXT("body_instance");
    }
    if (!PhysicsAsset || !Body || !Property)
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : !Body ? TEXT("body_not_found") : TEXT("property_not_found"));
        return AIStudioJsonString(Root);
    }
    const TSharedPtr<FJsonValue> Value = AIStudioParseJsonValueOrString(ValueJson);
    FString Error;
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetPhysicsBodyProperty", "AIStudioBridge Set Physics Body Property"));
    PhysicsAsset->Modify();
    Body->Modify();
    const bool bApplied = AIStudioSetPropertyOnContainerFromJsonValue(
        PropertyContainer,
        Body,
        Property,
        Value.Get(),
        Error);
    if (bApplied)
    {
        Body->PostEditChange();
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = bApplied && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("property_set_and_saved") : TEXT("property_set_failed"));
    Root->SetStringField(TEXT("body_name"), Body->BoneName.ToString());
    Root->SetStringField(TEXT("property_name"), Property->GetName());
    Root->SetStringField(TEXT("property_scope"), PropertyScope);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetObjectField(TEXT("readback"), AIStudioContainerPropertyValue(PropertyContainer, Body, Property));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetPhysicsConstraintProperty(
    const FString& PhysicsAssetPath,
    FName ConstraintName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_physics_constraint_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_physics_constraint_property(physics_asset_path, constraint_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    UPhysicsConstraintTemplate* Constraint = nullptr;
    if (PhysicsAsset)
    {
        const TObjectPtr<UPhysicsConstraintTemplate>* Match = PhysicsAsset->ConstraintSetup.FindByPredicate(
            [ConstraintName](const TObjectPtr<UPhysicsConstraintTemplate>& Candidate)
            {
                return Candidate && Candidate->GetFName() == ConstraintName;
            });
        Constraint = Match ? Match->Get() : nullptr;
    }
    void* PropertyContainer = Constraint;
    FProperty* Property = Constraint ? AIStudioFindFlexibleProperty(Constraint->GetClass(), PropertyName) : nullptr;
    FString PropertyScope = TEXT("constraint_template");
    if (Constraint && !Property)
    {
        PropertyContainer = &Constraint->DefaultInstance;
        Property = AIStudioFindFlexibleProperty(FConstraintInstance::StaticStruct(), PropertyName);
        PropertyScope = TEXT("constraint_instance");
    }
    if (Constraint && !Property)
    {
        PropertyContainer = &Constraint->DefaultInstance.ProfileInstance;
        Property = AIStudioFindFlexibleProperty(FConstraintProfileProperties::StaticStruct(), PropertyName);
        PropertyScope = TEXT("constraint_profile");
    }
    if (!PhysicsAsset || !Constraint || !Property)
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : !Constraint ? TEXT("constraint_not_found") : TEXT("property_not_found"));
        return AIStudioJsonString(Root);
    }
    const TSharedPtr<FJsonValue> Value = AIStudioParseJsonValueOrString(ValueJson);
    FString Error;
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetPhysicsConstraintProperty", "AIStudioBridge Set Physics Constraint Property"));
    PhysicsAsset->Modify();
    Constraint->Modify();
    const bool bApplied = AIStudioSetPropertyOnContainerFromJsonValue(
        PropertyContainer,
        Constraint,
        Property,
        Value.Get(),
        Error);
    if (bApplied)
    {
        Constraint->PostEditChange();
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = bApplied && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("property_set_and_saved") : TEXT("property_set_failed"));
    Root->SetStringField(TEXT("constraint_name"), Constraint->GetName());
    Root->SetStringField(TEXT("property_name"), Property->GetName());
    Root->SetStringField(TEXT("property_scope"), PropertyScope);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetObjectField(TEXT("readback"), AIStudioContainerPropertyValue(PropertyContainer, Constraint, Property));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetPhysicsProfileProperty(
    const FString& PhysicsAssetPath,
    FName ProfileName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_physics_profile_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_physics_profile_property(physics_asset_path, profile_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    const TSharedPtr<FJsonValue> Value = AIStudioParseJsonValueOrString(ValueJson);
    int32 PhysicalAnimationChanges = 0;
    int32 ConstraintChanges = 0;
    TArray<FString> Errors;
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetPhysicsProfileProperty", "AIStudioBridge Set Physics Profile Property"));
    PhysicsAsset->Modify();
    for (USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
    {
        FPhysicalAnimationProfile* Profile = Body ? Body->FindPhysicalAnimationProfile(ProfileName) : nullptr;
        FProperty* Property = Profile
            ? AIStudioFindFlexibleProperty(FPhysicalAnimationData::StaticStruct(), PropertyName)
            : nullptr;
        if (!Profile || !Property)
        {
            continue;
        }
        FString Error;
        Body->Modify();
        if (AIStudioSetPropertyOnContainerFromJsonValue(
            &Profile->PhysicalAnimationData,
            Body,
            Property,
            Value.Get(),
            Error))
        {
            ++PhysicalAnimationChanges;
            Body->PostEditChange();
        }
        else
        {
            Errors.Add(Error);
        }
    }
    for (UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
    {
        if (!Constraint)
        {
            continue;
        }
        for (FPhysicsConstraintProfileHandle& Handle : Constraint->ProfileHandles)
        {
            if (Handle.ProfileName != ProfileName)
            {
                continue;
            }
            FProperty* Property = AIStudioFindFlexibleProperty(FConstraintProfileProperties::StaticStruct(), PropertyName);
            if (!Property)
            {
                continue;
            }
            FString Error;
            Constraint->Modify();
            if (AIStudioSetPropertyOnContainerFromJsonValue(
                &Handle.ProfileProperties,
                Constraint,
                Property,
                Value.Get(),
                Error))
            {
                ++ConstraintChanges;
                Constraint->PostEditChange();
            }
            else
            {
                Errors.Add(Error);
            }
        }
    }
    const int32 TotalChanges = PhysicalAnimationChanges + ConstraintChanges;
    if (TotalChanges > 0)
    {
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = TotalChanges > 0 && Errors.Num() == 0 && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(
        TEXT("status"),
        bSaved ? TEXT("profile_property_set_and_saved") : TotalChanges == 0 ? TEXT("profile_or_property_not_found") : TEXT("profile_property_set_failed"));
    Root->SetNumberField(TEXT("physical_animation_changes"), PhysicalAnimationChanges);
    Root->SetNumberField(TEXT("constraint_changes"), ConstraintChanges);
    TArray<TSharedPtr<FJsonValue>> ErrorValues;
    for (const FString& Error : Errors)
    {
        ErrorValues.Add(MakeShared<FJsonValueString>(Error));
    }
    Root->SetArrayField(TEXT("errors"), ErrorValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::ListPhysicsProfiles(const FString& PhysicsAssetPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("list_physics_profiles"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.list_physics_profiles(physics_asset_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> PhysicalAnimationProfiles;
    for (const FName ProfileName : PhysicsAsset->GetPhysicalAnimationProfileNames())
    {
        int32 AssignmentCount = 0;
        for (const USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
        {
            AssignmentCount += Body && Body->FindPhysicalAnimationProfile(ProfileName) ? 1 : 0;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("name"), ProfileName.ToString());
        Row->SetNumberField(TEXT("assignment_count"), AssignmentCount);
        PhysicalAnimationProfiles.Add(MakeShared<FJsonValueObject>(Row));
    }
    TArray<TSharedPtr<FJsonValue>> ConstraintProfiles;
    for (const FName ProfileName : PhysicsAsset->GetConstraintProfileNames())
    {
        int32 AssignmentCount = 0;
        for (const UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
        {
            AssignmentCount += Constraint && Constraint->ContainsConstraintProfile(ProfileName) ? 1 : 0;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("name"), ProfileName.ToString());
        Row->SetNumberField(TEXT("assignment_count"), AssignmentCount);
        ConstraintProfiles.Add(MakeShared<FJsonValueObject>(Row));
    }
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("status"), TEXT("profiles_inspected"));
    Root->SetStringField(TEXT("asset_path"), PhysicsAsset->GetPathName());
    Root->SetArrayField(TEXT("physical_animation_profiles"), PhysicalAnimationProfiles);
    Root->SetArrayField(TEXT("constraint_profiles"), ConstraintProfiles);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPhysicsProfile(
    const FString& PhysicsAssetPath,
    FName ProfileName,
    const FString& ProfileType,
    bool bAssignAll)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_physics_profile"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_physics_profile(physics_asset_path, profile_name, profile_type, assign_all)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    const FString NormalizedType = ProfileType.TrimStartAndEnd().ToLower();
    const bool bPhysicalAnimation = NormalizedType == TEXT("physical_animation") || NormalizedType == TEXT("physical");
    const bool bConstraint = NormalizedType == TEXT("constraint") || NormalizedType == TEXT("constraints");
    if (!PhysicsAsset || ProfileName.IsNone() || (!bPhysicalAnimation && !bConstraint))
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : ProfileName.IsNone() ? TEXT("profile_name_required") : TEXT("invalid_profile_type"));
        return AIStudioJsonString(Root);
    }
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "AddPhysicsProfile", "AIStudioBridge Add Physics Profile"));
    PhysicsAsset->Modify();
    int32 AssignmentCount = 0;
    bool bCreated = false;
    if (bPhysicalAnimation)
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetPhysicalAnimationProfileNames());
        bCreated = !Names.Contains(ProfileName);
        Names.AddUnique(ProfileName);
        if (bAssignAll)
        {
            for (USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
            {
                if (!Body || Body->FindPhysicalAnimationProfile(ProfileName))
                {
                    AssignmentCount += Body ? 1 : 0;
                    continue;
                }
                Body->Modify();
                Body->CurrentPhysicalAnimationProfile = FPhysicalAnimationProfile();
                Body->AddPhysicalAnimationProfile(ProfileName);
                Body->PostEditChange();
                ++AssignmentCount;
            }
        }
    }
    else
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetConstraintProfileNames());
        bCreated = !Names.Contains(ProfileName);
        Names.AddUnique(ProfileName);
        if (bAssignAll)
        {
            for (UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
            {
                if (!Constraint || Constraint->ContainsConstraintProfile(ProfileName))
                {
                    AssignmentCount += Constraint ? 1 : 0;
                    continue;
                }
                Constraint->Modify();
                Constraint->AddConstraintProfile(ProfileName);
                Constraint->PostEditChange();
                ++AssignmentCount;
            }
        }
    }
    PhysicsAsset->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? (bCreated ? TEXT("profile_created_and_saved") : TEXT("profile_already_exists")) : TEXT("profile_save_failed"));
    Root->SetStringField(TEXT("profile_name"), ProfileName.ToString());
    Root->SetStringField(TEXT("profile_type"), bPhysicalAnimation ? TEXT("physical_animation") : TEXT("constraint"));
    Root->SetBoolField(TEXT("assign_all"), bAssignAll);
    Root->SetNumberField(TEXT("assignment_count"), AssignmentCount);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemovePhysicsProfile(
    const FString& PhysicsAssetPath,
    FName ProfileName,
    const FString& ProfileType)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_physics_profile"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_physics_profile(physics_asset_path, profile_name, profile_type)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    const FString NormalizedType = ProfileType.TrimStartAndEnd().ToLower();
    const bool bPhysicalAnimation = NormalizedType == TEXT("physical_animation") || NormalizedType == TEXT("physical");
    const bool bConstraint = NormalizedType == TEXT("constraint") || NormalizedType == TEXT("constraints");
    if (!PhysicsAsset || ProfileName.IsNone() || (!bPhysicalAnimation && !bConstraint))
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : ProfileName.IsNone() ? TEXT("profile_name_required") : TEXT("invalid_profile_type"));
        return AIStudioJsonString(Root);
    }
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "RemovePhysicsProfile", "AIStudioBridge Remove Physics Profile"));
    PhysicsAsset->Modify();
    int32 RemovedAssignments = 0;
    int32 RemovedNames = 0;
    if (bPhysicalAnimation)
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetPhysicalAnimationProfileNames());
        RemovedNames = Names.Remove(ProfileName);
        for (USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
        {
            if (!Body || !Body->FindPhysicalAnimationProfile(ProfileName))
            {
                continue;
            }
            Body->Modify();
            Body->RemovePhysicalAnimationProfile(ProfileName);
            Body->PostEditChange();
            ++RemovedAssignments;
        }
    }
    else
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetConstraintProfileNames());
        RemovedNames = Names.Remove(ProfileName);
        for (UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
        {
            if (!Constraint || !Constraint->ContainsConstraintProfile(ProfileName))
            {
                continue;
            }
            Constraint->Modify();
            Constraint->RemoveConstraintProfile(ProfileName);
            Constraint->PostEditChange();
            ++RemovedAssignments;
        }
    }
    if (RemovedNames > 0 || RemovedAssignments > 0)
    {
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = (RemovedNames > 0 || RemovedAssignments > 0) && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("profile_removed_and_saved") : TEXT("profile_not_found"));
    Root->SetStringField(TEXT("profile_name"), ProfileName.ToString());
    Root->SetStringField(TEXT("profile_type"), bPhysicalAnimation ? TEXT("physical_animation") : TEXT("constraint"));
    Root->SetNumberField(TEXT("removed_assignments"), RemovedAssignments);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

static void AIStudioAppendNiagaraErrors(
    const FNiagaraExternalEditContext& Context,
    const TSharedRef<FJsonObject>& Root)
{
    TArray<TSharedPtr<FJsonValue>> Errors;
    for (const FText& Error : Context.Errors)
    {
        Errors.Add(MakeShared<FJsonValueString>(Error.ToString()));
    }
    Root->SetArrayField(TEXT("errors"), Errors);
}

static bool AIStudioSetInstancedStructValue(
    FInstancedStruct& Value,
    const FString& ValueJson,
    FString& OutError)
{
    const UScriptStruct* Struct = Value.GetScriptStruct();
    void* Memory = Value.GetMutableMemory();
    if (!Struct || !Memory)
    {
        OutError = TEXT("Niagara value has no concrete script struct.");
        return false;
    }

    TSharedPtr<FJsonValue> Parsed;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ValueJson);
    if (!FJsonSerializer::Deserialize(Reader, Parsed) || !Parsed.IsValid())
    {
        Parsed = MakeShared<FJsonValueString>(ValueJson);
    }
    TSharedRef<FJsonObject> Object = MakeShared<FJsonObject>();
    if (Parsed->Type == EJson::Object)
    {
        Object = Parsed->AsObject().ToSharedRef();
    }
    else if (Parsed->Type == EJson::Array)
    {
        const TArray<TSharedPtr<FJsonValue>>& Values = Parsed->AsArray();
        const TCHAR* Names[] = {TEXT("X"), TEXT("Y"), TEXT("Z"), TEXT("W")};
        for (int32 Index = 0; Index < FMath::Min(Values.Num(), 4); ++Index)
        {
            Object->SetField(Names[Index], Values[Index]);
        }
        if (Struct == TBaseStructure<FLinearColor>::Get())
        {
            const TArray<TSharedPtr<FJsonValue>> Copy = Values;
            Object = MakeShared<FJsonObject>();
            const TCHAR* ColorNames[] = {TEXT("R"), TEXT("G"), TEXT("B"), TEXT("A")};
            for (int32 Index = 0; Index < FMath::Min(Copy.Num(), 4); ++Index)
            {
                Object->SetField(ColorNames[Index], Copy[Index]);
            }
        }
    }
    else
    {
        Object->SetField(TEXT("Value"), Parsed);
    }
    FText FailReason;
    const bool bConverted = FJsonObjectConverter::JsonObjectToUStruct(
        Object,
        Struct,
        Memory,
        0,
        0,
        false,
        &FailReason);
    OutError = FailReason.ToString();
    return bConverted;
}

static TSharedRef<FJsonObject> AIStudioInstancedStructValueJson(const FInstancedStruct& Value)
{
    const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    const UScriptStruct* Struct = Value.GetScriptStruct();
    const void* Memory = Value.GetMemory();
    Row->SetStringField(TEXT("type"), Struct ? Struct->GetPathName() : TEXT(""));
    if (!Struct || !Memory)
    {
        Row->SetObjectField(TEXT("value"), MakeShared<FJsonObject>());
        return Row;
    }
    FString Json;
    FJsonObjectConverter::UStructToJsonObjectString(Struct, Memory, Json, 0, 0);
    TSharedPtr<FJsonObject> Parsed = AIStudioParseJsonObject(Json);
    Row->SetObjectField(TEXT("value"), Parsed.IsValid() ? Parsed.ToSharedRef() : MakeShared<FJsonObject>());
    Row->SetStringField(TEXT("exported_json"), Json);
    return Row;
}

static bool AIStudioMergeJsonProperty(
    FString& PropertyValues,
    FName PropertyName,
    const FString& ValueJson,
    FString& OutError)
{
    TSharedPtr<FJsonObject> Object = AIStudioParseJsonObject(PropertyValues);
    if (!Object.IsValid())
    {
        OutError = TEXT("Niagara property data was not a JSON object.");
        return false;
    }
    TSharedPtr<FJsonValue> Parsed;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ValueJson);
    if (!FJsonSerializer::Deserialize(Reader, Parsed) || !Parsed.IsValid())
    {
        Parsed = MakeShared<FJsonValueString>(ValueJson);
    }
    Object->SetField(PropertyName.ToString(), Parsed);
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&PropertyValues);
    return FJsonSerializer::Serialize(Object.ToSharedRef(), Writer);
}

FString UAIStudioBridgeLibrary::ListNiagaraModuleInputs(const FString& SystemPath, FName EmitterName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("list_niagara_module_inputs"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.list_niagara_module_inputs(system_path, emitter_name)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    if (!System)
    {
        Root->SetStringField(TEXT("status"), TEXT("system_not_found"));
        return AIStudioJsonString(Root);
    }
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_SystemSummary Summary;
    UNiagaraExternalEditUtilities::GetSystemSummary(System, Summary, Context);
    TArray<TSharedPtr<FJsonValue>> Emitters;
    for (const FNiagaraExt_EmitterSummary& Emitter : Summary.Emitters)
    {
        if (!EmitterName.IsNone() && Emitter.EmitterName != EmitterName)
        {
            continue;
        }
        FNiagaraExt_StackItemReference Ref(System, Emitter.EmitterName);
        FNiagaraExt_EmitterTopology Topology;
        TArray<FNiagaraExt_ModuleInputValues> Values;
        UNiagaraExternalEditUtilities::GetEmitterTopology(Ref, Topology, Context);
        UNiagaraExternalEditUtilities::GetEmitterInputValues(Ref, Values, Context);
        FString TopologyJson;
        FJsonObjectConverter::UStructToJsonObjectString(FNiagaraExt_EmitterTopology::StaticStruct(), &Topology, TopologyJson, 0, 0);
        TArray<TSharedPtr<FJsonValue>> InputValues;
        for (const FNiagaraExt_ModuleInputValues& Value : Values)
        {
            const TSharedRef<FJsonObject> ValueObject = MakeShared<FJsonObject>();
            ValueObject->SetStringField(TEXT("moduleName"), Value.ModuleName.ToString());
            TArray<TSharedPtr<FJsonValue>> Inputs;
            for (const FNiagaraExt_StackInputValueEntry& Input : Value.Inputs)
            {
                const TSharedRef<FJsonObject> InputObject = MakeShared<FJsonObject>();
                InputObject->SetStringField(TEXT("name"), Input.Name.ToString());
                InputObject->SetObjectField(TEXT("value"), AIStudioInstancedStructValueJson(Input.Value));
                Inputs.Add(MakeShared<FJsonValueObject>(InputObject));
            }
            ValueObject->SetArrayField(TEXT("inputs"), Inputs);
            InputValues.Add(MakeShared<FJsonValueObject>(ValueObject));
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("emitter_name"), Emitter.EmitterName.ToString());
        Row->SetStringField(TEXT("topology_json"), TopologyJson);
        Row->SetArrayField(TEXT("input_values"), InputValues);
        Emitters.Add(MakeShared<FJsonValueObject>(Row));
    }
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetArrayField(TEXT("emitters"), Emitters);
    Root->SetNumberField(TEXT("emitter_count"), Emitters.Num());
    Root->SetBoolField(TEXT("ok"), !Context.HasErrors() && Emitters.Num() > 0);
    Root->SetStringField(TEXT("status"), Context.HasErrors() ? TEXT("inspection_failed") : TEXT("inspected"));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraUserParameter(
    const FString& SystemPath,
    FName ParameterName,
    const FString& ValueJson,
    const FString& ValueType)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_user_parameter"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_user_parameter(system_path, parameter_name, value_json, value_type)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    if (!System)
    {
        Root->SetStringField(TEXT("status"), TEXT("system_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString TypeKey = ValueType.ToLower();
    const FNiagaraTypeDefinition* Type = &FNiagaraTypeDefinition::GetFloatDef();
    if (TypeKey == TEXT("bool") || TypeKey == TEXT("boolean")) Type = &FNiagaraTypeDefinition::GetBoolDef();
    else if (TypeKey == TEXT("int") || TypeKey == TEXT("int32")) Type = &FNiagaraTypeDefinition::GetIntDef();
    else if (TypeKey == TEXT("vector") || TypeKey == TEXT("vec3")) Type = &FNiagaraTypeDefinition::GetVec3Def();
    else if (TypeKey == TEXT("position")) Type = &FNiagaraTypeDefinition::GetPositionDef();
    else if (TypeKey == TEXT("color") || TypeKey == TEXT("linearcolor")) Type = &FNiagaraTypeDefinition::GetColorDef();

    FNiagaraExt_UserVariable Variable;
    Variable.Name = FName(*FString::Printf(TEXT("User.%s"), *ParameterName.ToString().Replace(TEXT("User."), TEXT(""))));
    Variable.Type = *Type;
    Variable.DefaultValue.InitializeAs(Type->GetScriptStruct());
    FString Error;
    if (!AIStudioSetInstancedStructValue(Variable.DefaultValue, ValueJson, Error))
    {
        Root->SetStringField(TEXT("status"), TEXT("value_parse_failed"));
        Root->SetStringField(TEXT("error"), Error);
        return AIStudioJsonString(Root);
    }
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_Variable Existing;
    Existing.Name = Variable.Name;
    Existing.Type = Variable.Type;
    UNiagaraExternalEditUtilities::RemoveUserVariable(System, Existing, Context);
    Context.Errors.Reset();
    UNiagaraExternalEditUtilities::AddUserVariable(System, Variable, Context);
    FNiagaraExt_UserVariables ReadbackVariables;
    if (!Context.HasErrors())
    {
        UNiagaraExternalEditUtilities::GetUserVariables(System, ReadbackVariables, Context);
    }
    const FNiagaraExt_UserVariable* Readback = ReadbackVariables.UserVariables.FindByPredicate(
        [&Variable](const FNiagaraExt_UserVariable& Candidate)
        {
            return Candidate.Name == Variable.Name && Candidate.Type == Variable.Type;
        });
    const bool bSaved = !Context.HasErrors() && Readback && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("parameter_set_and_saved") : TEXT("parameter_set_failed"));
    Root->SetStringField(TEXT("parameter_name"), Variable.Name.ToString());
    Root->SetStringField(TEXT("value_type"), TypeKey);
    if (Readback)
    {
        Root->SetObjectField(TEXT("readback"), AIStudioInstancedStructValueJson(Readback->DefaultValue));
    }
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraRendererProperty(
    const FString& SystemPath,
    FName EmitterName,
    int32 RendererIndex,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_renderer_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_renderer_property(system_path, emitter_name, renderer_index, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName);
    Ref.RendererIndex = RendererIndex;
    FNiagaraExt_RendererData Data;
    if (System) UNiagaraExternalEditUtilities::GetRendererData(Ref, Data, Context);
    FString Error;
    if (!Context.HasErrors() && AIStudioMergeJsonProperty(Data.PropertyValues, PropertyName, ValueJson, Error))
    {
        UNiagaraExternalEditUtilities::SetRendererData(Ref, Data, Context);
    }
    FNiagaraExt_RendererData Readback;
    if (!Context.HasErrors() && Error.IsEmpty())
    {
        UNiagaraExternalEditUtilities::GetRendererData(Ref, Readback, Context);
    }
    const TSharedPtr<FJsonObject> ReadbackObject = AIStudioParseJsonObject(Readback.PropertyValues);
    const bool bHasReadback = ReadbackObject.IsValid() && ReadbackObject->HasField(PropertyName.ToString());
    const bool bSaved = !Context.HasErrors() && Error.IsEmpty() && bHasReadback && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("renderer_property_set_and_saved") : TEXT("renderer_property_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("readback_json"), Readback.PropertyValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraModuleInput(
    const FString& SystemPath,
    FName EmitterName,
    FName ScriptName,
    FName ModuleName,
    FName InputName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_module_input"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_module_input(system_path, emitter_name, script_name, module_name, input_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName, ScriptName, ModuleName);
    Ref.InputNameStack.Add(InputName);
    FNiagaraExt_StackInputTopology Topology;
    FNiagaraExt_StackInputValue Data;
    if (System)
    {
        UNiagaraExternalEditUtilities::GetStackInputTopology(Ref, Topology, Context);
        UNiagaraExternalEditUtilities::GetStackInputData(Ref, Data, Context);
    }
    FString Error;
    bool bSetRequested = false;
    if (!Topology.bIsEditable)
    {
        Error = TEXT("The requested Niagara stack input is not editable in the current stack state.");
    }
    else if (!Context.HasErrors() && AIStudioSetInstancedStructValue(Data, ValueJson, Error))
    {
        UNiagaraExternalEditUtilities::SetStackInputData(Ref, Data, Context);
        bSetRequested = true;
    }
    FNiagaraExt_StackInputValue Readback;
    if (bSetRequested && !Context.HasErrors())
    {
        UNiagaraExternalEditUtilities::GetStackInputData(Ref, Readback, Context);
    }
    const bool bHasReadback = Readback.GetScriptStruct() != nullptr && Readback.GetMemory() != nullptr;
    const bool bSaved = bSetRequested
        && bHasReadback
        && !Context.HasErrors()
        && Error.IsEmpty()
        && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("module_input_set_and_saved") : TEXT("module_input_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("input_name"), InputName.ToString());
    Root->SetObjectField(TEXT("readback"), AIStudioInstancedStructValueJson(Readback));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemoveNiagaraEmitter(const FString& SystemPath, FName EmitterName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_niagara_emitter"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_niagara_emitter(system_path, emitter_name)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName);
    if (System) UNiagaraExternalEditUtilities::RemoveEmitter(Ref, Context);
    FNiagaraExt_SystemSummary Readback;
    if (!Context.HasErrors())
    {
        UNiagaraExternalEditUtilities::GetSystemSummary(System, Readback, Context);
    }
    const bool bRemoved = !Readback.Emitters.ContainsByPredicate(
        [EmitterName](const FNiagaraExt_EmitterSummary& Emitter)
        {
            return Emitter.EmitterName == EmitterName;
        });
    const bool bSaved = !Context.HasErrors() && bRemoved && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("emitter_removed_and_saved") : TEXT("emitter_remove_failed"));
    Root->SetBoolField(TEXT("removed"), bRemoved);
    Root->SetNumberField(TEXT("emitter_count"), Readback.Emitters.Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraEmitterProperty(
    const FString& SystemPath,
    FName EmitterName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_emitter_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_emitter_property(system_path, emitter_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName);
    FNiagaraExt_EmitterData Data;
    if (System) UNiagaraExternalEditUtilities::GetEmitterData(Ref, Data, Context);
    FString Error;
    if (!Context.HasErrors() && AIStudioMergeJsonProperty(Data.PropertyValues, PropertyName, ValueJson, Error))
    {
        UNiagaraExternalEditUtilities::SetEmitterData(Ref, Data, Context);
    }
    FNiagaraExt_EmitterData Readback;
    if (!Context.HasErrors() && Error.IsEmpty())
    {
        UNiagaraExternalEditUtilities::GetEmitterData(Ref, Readback, Context);
    }
    const TSharedPtr<FJsonObject> ReadbackObject = AIStudioParseJsonObject(Readback.PropertyValues);
    const bool bHasReadback = ReadbackObject.IsValid() && ReadbackObject->HasField(PropertyName.ToString());
    const bool bSaved = !Context.HasErrors() && Error.IsEmpty() && bHasReadback && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("emitter_property_set_and_saved") : TEXT("emitter_property_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("readback_json"), Readback.PropertyValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}
