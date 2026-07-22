#include "AIStudioBridgeLibrary.h"

#if WITH_EDITOR
#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "BlueprintActionDatabase.h"
#include "BlueprintActionFilter.h"
#include "BlueprintNodeSpawner.h"
#include "Components/ActorComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "InputKeyEventArgs.h"
#include "UObject/UnrealType.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#endif

static FString AIStudioJsonString(const TSharedRef<FJsonObject>& Object)
{
    FString Output;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Object, Writer);
    return Output;
}

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
    Graphs.Append(AnimBlueprint->UbergraphPages);
    Graphs.Append(AnimBlueprint->FunctionGraphs);
    Graphs.Append(AnimBlueprint->MacroGraphs);
    Graphs.Append(AnimBlueprint->DelegateSignatureGraphs);

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

FString UAIStudioBridgeLibrary::InspectAnimationSequence(UAnimSequence* Animation)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_animation_sequence"));
    Root->SetBoolField(TEXT("ok"), Animation != nullptr);
    if (!Animation)
    {
        Root->SetStringField(TEXT("error"), TEXT("Animation was null."));
        return AIStudioJsonString(Root);
    }

    Root->SetStringField(TEXT("asset_name"), Animation->GetName());
    Root->SetStringField(TEXT("asset_path"), Animation->GetPathName());
    Root->SetStringField(TEXT("skeleton"), Animation->GetSkeleton() ? Animation->GetSkeleton()->GetPathName() : TEXT(""));
    Root->SetNumberField(TEXT("play_length_seconds"), Animation->GetPlayLength());
    Root->SetNumberField(TEXT("sampled_keys"), Animation->GetNumberOfSampledKeys());
    Root->SetNumberField(TEXT("sample_rate_fps"), Animation->GetSamplingFrameRate().AsDecimal());
    Root->SetBoolField(TEXT("has_root_motion"), Animation->HasRootMotion());
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_animation_sequence(animation)"));
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
